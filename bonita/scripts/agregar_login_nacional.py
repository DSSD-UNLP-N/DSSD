"""Hace que los conectores de Bonita entren a la API Nacional con JWT, sin abrir Studio.

La API Nacional exige `Authorization: Bearer <token>`. Bonita no puede guardar un token de larga vida (vence), así que
cada tarea de servicio que llama a Nacional empieza con un conector nuevo, `loginNacional`, que hace `POST /login` con la
cuenta de servicio de Bonita y deja la respuesta en la variable `nacionalLoginJson`. El conector que sigue manda el token
en la cabecera `Authorization`. Como se vuelve a entrar en cada tarea, el token nunca está vencido (las ventanas de
ofertas duran horas).

  Validar en Sistema Nacional y Calcular Cobertura              loginNacional → evaluarOfertas
  Notificar Adjudicacion y Registrar Compromiso Nacional        loginNacional → resolverReservas
  Liberar Recursos y Notificar Cierre                           loginNacional → cerrarAdjudicaciones

Clona el conector REST `evaluarOfertas` (así queda con la misma configuración que los demás) y cambia solo lo que difiere.
Las URLs y la clave están escritas en los conectores igual que el resto (X-Api-Key, URLs de localhost): llevarlas a
parámetros del proceso es el trabajo de «Local vs Production» (WP12). Para la nube hay que cambiar acá USUARIO y CLAVE.

No modifica el archivo de entrada: escribe uno nuevo para importarlo en Studio (Archivo > Importar) y volver a ejecutar.
Si una tarea ya tiene `loginNacional`, no hace nada. Se aplica sobre un .bos que ya tenga los conectores de cierre
(`agregar_conector_cierre.py`).

    python bonita/scripts/agregar_login_nacional.py entrega-3/entrega41_cierre.bos entrega-3/entrega41_cierre_jwt.bos
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agregar_conector_cierre import atributo, bloque, clonar, id_nuevo  # noqa: E402

URL_LOGIN = "http://localhost:8002/login"
USUARIO = "bonita-service"
CLAVE = "change-me"
VARIABLE = "nacionalLoginJson"
PLANTILLA = "evaluarOfertas"

# tarea de servicio -> conector que llama a Nacional y necesita el token
TAREAS = {
    "Validar en Sistema Nacional y Calcular Cobertura": "evaluarOfertas",
    "Notificar Adjudicacion y Registrar Compromiso Nacional": "resolverReservas",
    "Liberar Recursos y Notificar Cierre": "cerrarAdjudicaciones",
}

BODY_LOGIN = f'groovy.json.JsonOutput.toJson([username: "{USUARIO}", password: "{CLAVE}"])'
TOKEN = f"new groovy.json.JsonSlurper().parseText({VARIABLE}).access_token"
CABECERA = f'"Bearer " + {TOKEN}'


def elemento(x: str, tag: str, nombre: str, desde: int = 0) -> tuple[int, int]:
    m = re.compile(rf'<{tag} [^>]*\bname="{re.escape(nombre)}"').search(x, desde)
    if not m:
        raise ValueError(f"No está <{tag} name=\"{nombre}\">")
    return m.start(), bloque(x, m.start(), tag)


def agregar_variable(proc: str) -> str:
    """Una variable de proceso de texto para guardar la respuesta del login (clon de evaluacionJson)."""
    if re.search(rf'<data [^>]*\bname="{VARIABLE}"', proc):
        raise ValueError(f"Ya existe la variable {VARIABLE}")
    ini, fin = elemento(proc, "data", "evaluacionJson")
    copia = clonar(proc[ini:fin], "evaluacionJson", VARIABLE)
    return proc[:fin] + "\r\n      " + copia + proc[fin:]


def conector_login(proc: str) -> str:
    ini, fin = elemento(proc, "connectors", PLANTILLA)
    texto = clonar(proc[ini:fin], PLANTILLA, "loginNacional")
    texto = texto.replace("http://localhost:8002/evaluaciones", URL_LOGIN)
    texto = re.sub(r'(key="body">\s*<expression [^>]*?\bcontent=")[^"]*(")', lambda m: m.group(1) + atributo(BODY_LOGIN) + m.group(2), texto, count=1)
    texto = re.sub(r'\s*<referencedElements [^>]*\bname="ofertasJson"[^>]*/>', "", texto)
    return texto.replace("evaluacionJson", VARIABLE)


def tabla_cabeceras() -> str:
    ref = (f'<referencedElements xmi:type="process:Data" xmi:id="{id_nuevo()}" name="{VARIABLE}" '
           f'dataType="_iDGYxaxXEfGR3cB9VRwXjA"/>')
    return (f'<expression xmi:type="expression:TableExpression" xmi:id="{id_nuevo()}">\r\n'
            f'                  <expressions xmi:type="expression:ListExpression" xmi:id="{id_nuevo()}">\r\n'
            f'                    <expressions xmi:type="expression:Expression" xmi:id="{id_nuevo()}" name="Authorization" content="Authorization"/>\r\n'
            f'                    <expressions xmi:type="expression:Expression" xmi:id="{id_nuevo()}" name="Bearer" content="{atributo(CABECERA)}" '
            f'interpreter="GROOVY" type="TYPE_READ_ONLY_SCRIPT" returnTypeFixed="true">\r\n'
            f'                      {ref}\r\n'
            f'                    </expressions>\r\n'
            f'                  </expressions>\r\n'
            f'                </expression>')


def con_cabecera(conector: str) -> str:
    """Pone la cabecera Authorization en la tabla (vacía) de cabeceras del conector."""
    nuevo, n = re.subn(r'(key="urlHeaders">\s*)<expression xmi:type="expression:TableExpression" xmi:id="[^"]+"/>',
                       lambda m: m.group(1) + tabla_cabeceras(), conector, count=1)
    if n != 1:
        raise ValueError("El conector no tiene una tabla de cabeceras vacía")
    return nuevo


def agregar(proc: str) -> str:
    plantilla = conector_login(proc)
    proc = agregar_variable(proc)
    for tarea, nombre in TAREAS.items():
        t_ini, t_fin = elemento(proc, "elements", tarea)
        c_ini, c_fin = elemento(proc, "connectors", nombre, t_ini)
        if not t_ini < c_ini < t_fin:
            raise ValueError(f"El conector {nombre} no está en «{tarea}»")
        if 'name="loginNacional"' in proc[t_ini:t_fin]:
            raise ValueError(f"«{tarea}» ya tiene loginNacional")
        primero = proc.index("<connectors ", t_ini)
        llamada = con_cabecera(proc[c_ini:c_fin])
        login = clonar(plantilla, "loginNacional", "loginNacional")  # ids nuevos para cada tarea
        sangria = "\r\n          "
        proc = proc[:primero] + login + sangria + proc[primero:c_ini] + llamada + proc[c_fin:]
    return proc


def main(entrada: str, salida: str) -> None:
    with zipfile.ZipFile(entrada) as zin:
        nombre = next(n for n in zin.namelist() if n.endswith(".proc"))
        nuevo = agregar(zin.read(nombre).decode("utf-8"))
        minidom.parseString(nuevo.encode("utf-8"))  # que siga siendo XML válido
        with zipfile.ZipFile(salida, "w") as zout:
            for info in zin.infolist():
                datos = nuevo.encode("utf-8") if info.filename == nombre else zin.read(info.filename)
                zout.writestr(info, datos, compress_type=info.compress_type)
    print(f"Listo: {salida}")
    for tarea, nombre in TAREAS.items():
        print(f"  «{tarea}»: loginNacional -> {nombre} (con Authorization: Bearer)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
