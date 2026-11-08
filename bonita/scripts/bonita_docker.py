"""Levanta un Bonita Community 2025.2 en Docker con el proceso de RescueSync desplegado, sin Bonita Studio.

Sirve para correr los escenarios con Bonita real (`backend/scripts/correr_escenarios.py`, `preflight.py`, las pruebas de UI) en una
máquina Linux sin Studio (por ejemplo, un contenedor de la nube). Hace, desde cero y en este orden:

  1. Construye el `.bar` del proceso a partir del `.bos` (por defecto `entrega-3/entrega42_local.bos`) con Maven y el
     `bonita-project-maven-plugin` que trae el propio proyecto. Trabaja sobre una copia en un directorio temporal: el `.bos` no se toca.
     En la copia completa lo que Studio agrega solo al Ejecutar (ver `preparar_copia`).
  2. Arranca el contenedor `bonita` (imagen `bonita:2025.2`) con `--network host`: los conectores del proceso llaman a la app en
     `localhost:8001` y a la API Nacional en `localhost:8002`, que tienen que ser los del host.
  3. Entra como usuario técnico (`install`/`install`), importa la organización ACME del `.bos`, da a cada usuario todos los perfiles
     (lo mismo que hace Studio al desplegar la organización) y el perfil User al rol `representante_ong` (para las ONGs que crea la app).
  4. Despliega el `.bar` (el actor mapping viene adentro, el de `process_configurations/*.conf`) y habilita el proceso.

Requisitos: Docker con la imagen `bonita:2025.2` (`docker pull bonita:2025.2`), Java 17+ y Maven 3.9 (`mvn` en el PATH, o
`/opt/maven/bin/mvn`), acceso a Maven Central, Python 3.10+ con `requests`, y los puertos 8080 y 9000 libres en el host.

    python bonita/scripts/bonita_docker.py                    # crea el contenedor si no existe y despliega
    python bonita/scripts/bonita_docker.py --recrear          # borra el contenedor `bonita` y empieza de cero (H2 nuevo: casos en 0)
    python bonita/scripts/bonita_docker.py --bos entrega-3/entrega42_nube.bos --recrear

Diferencias con el Bonita de Studio: base H2 dentro del contenedor (se pierde con `--recrear`); las tareas humanas quedan sin
formulario (la app las completa por REST, no se usan desde el portal); el tope de 150 casos en 30 días cuenta por contenedor; la
imagen corre con el security manager ProGrade (`PRO_GRADE=true`), que Studio no usa. Diagnóstico: `docker logs bonita` (es el bonita.log).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[2]
BOS_POR_DEFECTO = RAIZ / "entrega-3" / "entrega42_local.bos"
BASE = "http://localhost:8080/bonita"
TECNICO = ("install", "install")
ROL_ONG = "representante_ong"


def paso(texto: str) -> None:
    print(f"\n== {texto}", flush=True)


def maven() -> str:
    for candidato in (os.environ.get("MVN"), shutil.which("mvn"), "/opt/maven/bin/mvn"):
        if candidato and Path(candidato).exists():
            return candidato
    sys.exit("No encuentro Maven: ponelo en el PATH o pasá MVN=/ruta/a/mvn")


def preparar_copia(app: Path) -> None:
    """Completa, en la copia extraída, lo que Studio agrega solo al Ejecutar y el plugin de Maven no.

    - La configuración `Local` (`process_configurations/*.conf`, la que trae el actor mapping) no lista las implementaciones de los
      conectores REST; sin ellas el `.bar` sale sin `connector/*.impl` y el proceso queda sin resolver («has no implementation»). Se
      copian de la configuración embebida en el `.proc` (la de `Production`, que sí las tiene).
    - Las tareas humanas no tienen formulario (la app las completa por REST). Sin formulario el mapeo queda INTERNAL vacío y el motor
      deja el proceso sin resolver; se marcan como «sin formulario» (NONE). El formulario de instanciación (`newForm`) no se toca.
    """
    proc = next(app.glob("diagrams/*.proc"))
    texto = proc.read_text(encoding="utf-8")
    texto, cambiados = re.subn(r'(<formMapping xmi:type="process:FormMapping" xmi:id="[^"]+")(>\s*<targetForm [^>]*content="")',
                               r'\1 type="NONE"\2', texto)
    proc.write_text(texto, encoding="utf-8")
    sin_ids = lambda xml: re.sub(r'\s+xmi:(?:type|id)="[^"]*"', "", xml)  # noqa: E731
    mapeos = sorted(set(sin_ids(m) for m in re.findall(r'<definitionMappings [^>]*type="CONNECTOR"[^>]*/>', texto)))
    dependencias = re.search(r'<processDependencies [^>]*id="CONNECTOR">.*?</processDependencies>', texto, re.S)
    for conf in app.glob("process_configurations/*.conf"):
        xml = conf.read_text(encoding="utf-8")
        if "<definitionMappings" not in xml and mapeos and dependencias:
            xml = xml.replace('<processDependencies id="CONNECTOR"/>', "\n".join(mapeos) + "\n" + sin_ids(dependencias.group(0)))
            conf.write_text(xml, encoding="utf-8")
    print(f"  {cambiados} tareas sin formulario; implementaciones de conectores: {len(mapeos)}")


def construir_bar(bos: Path, trabajo: Path) -> tuple[Path, Path]:
    """Devuelve (ruta del .bar, ruta de la organización ACME.xml) construidos desde una copia del .bos."""
    paso(f"Construyendo el .bar desde {bos.name}")
    with zipfile.ZipFile(bos) as z:
        z.extractall(trabajo)
    poms = [p for p in trabajo.glob("*/pom.xml")]
    if len(poms) != 1:
        sys.exit(f"Esperaba un solo proyecto en el .bos y encontré {len(poms)}")
    proyecto = poms[0].parent
    preparar_copia(proyecto / "app")
    settings = trabajo / "settings.xml"  # el plugin lanza un Maven anidado que exige un settings.xml de usuario
    settings.write_text("<settings/>\n", encoding="utf-8")
    # process-resources alcanza: el .bar se arma antes de compilar. Llegar a `package` pide groovy-eclipse-compiler, que solo está en
    # groovy.jfrog.io (y no hay código Groovy propio que compilar).
    comando = [maven(), "-B", "-ntp", "-s", str(settings), "-f", str(proyecto / "pom.xml"), "process-resources"]
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(resultado.stdout[-4000:])
        sys.exit("Falló el build del .bar con Maven (salida arriba)")
    bars = list(proyecto.glob("app/target/processes/*.bar"))
    if len(bars) != 1:
        sys.exit(f"Esperaba un .bar y encontré {bars}")
    organizacion = next(proyecto.glob("app/organizations/*.xml"))
    print(f"  {bars[0].name} ({bars[0].stat().st_size // 1024} KB), organización {organizacion.name}")
    return bars[0], organizacion


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def levantar_contenedor(imagen: str, recrear: bool) -> None:
    paso("Contenedor de Bonita")
    estado = docker("inspect", "-f", "{{.State.Running}}", "bonita", check=False)
    if estado.returncode == 0 and recrear:
        docker("rm", "-f", "bonita")
        print("  contenedor anterior borrado")
        estado = docker("inspect", "-f", "{{.State.Running}}", "bonita", check=False)
    if estado.returncode != 0:
        docker("run", "-d", "--name", "bonita", "--network", "host", imagen)
        print(f"  creado desde {imagen} (--network host)")
    elif estado.stdout.strip() != "true":
        docker("start", "bonita")
        print("  arrancado (ya existía)")
    else:
        print("  ya estaba corriendo")
    limite = time.time() + 300
    while time.time() < limite:
        try:
            if requests.get(f"{BASE}/", timeout=5).status_code == 200:
                print("  GET /bonita → 200")
                return
        except requests.RequestException:
            pass
        time.sleep(3)
    sys.exit("Bonita no respondió en 5 minutos: docker logs bonita")


class Bonita:
    def __init__(self, usuario: str, clave: str) -> None:
        self.s = requests.Session()
        r = self.s.post(f"{BASE}/loginservice", data={"username": usuario, "password": clave, "redirect": "false"}, timeout=30)
        if r.status_code not in (200, 204):
            sys.exit(f"Login de {usuario} → {r.status_code}")
        self.s.headers["X-Bonita-API-Token"] = self.s.cookies.get("X-Bonita-API-Token", "")

    def pedir(self, metodo: str, ruta: str, **kw) -> requests.Response:
        r = self.s.request(metodo, f"{BASE}{ruta}", timeout=120, **kw)
        if r.status_code >= 400:
            sys.exit(f"{metodo} {ruta} → {r.status_code}: {r.text[:500]}")
        return r

    def subir(self, servlet: str, archivo: Path) -> str:
        with archivo.open("rb") as f:
            # Sin tipo MIME el servlet falla (columna MIMETYPE NOT NULL en la base de Bonita).
            return self.pedir("POST", f"/portal/{servlet}", files={"file": (archivo.name, f, "application/octet-stream")}).text.strip()

    def todos(self, ruta: str, **params) -> list[dict]:
        return self.pedir("GET", ruta, params={"p": 0, "c": 500, **params}).json()


def importar_organizacion(b: Bonita, organizacion: Path) -> None:
    paso("Organización")
    tmp = b.subir("organizationUpload", organizacion)
    b.pedir("POST", "/services/organization/import", data={"organizationDataUpload": tmp, "importPolicy": "MERGE_DUPLICATES"})
    usuarios = b.todos("/API/identity/user")
    print(f"  importada: {len(usuarios)} usuarios ({', '.join(sorted(u['userName'] for u in usuarios))})")


def asignar_perfiles(b: Bonita) -> None:
    paso("Perfiles")
    perfiles = {p["name"]: p["id"] for p in b.todos("/API/portal/profile")}
    for nombre, perfil_id in perfiles.items():
        actuales = b.todos("/API/portal/profileMember", f=[f"profile_id={perfil_id}", "member_type=user"])
        ya = {m["user_id"] for m in actuales}
        for u in b.todos("/API/identity/user"):
            if u["id"] not in ya:
                b.pedir("POST", "/API/portal/profileMember", json={"profile_id": perfil_id, "member_type": "user", "user_id": u["id"]})
    print(f"  todos los usuarios con {', '.join(perfiles)} (como Studio)")
    roles = b.todos("/API/identity/role", f=f"name={ROL_ONG}")
    if roles:
        actuales = b.todos("/API/portal/profileMember", f=[f"profile_id={perfiles['User']}", "member_type=role"])
        if roles[0]["id"] not in {m["role_id"] for m in actuales}:
            b.pedir("POST", "/API/portal/profileMember",
                    json={"profile_id": perfiles["User"], "member_type": "role", "role_id": roles[0]["id"]})
        print(f"  perfil User también para el rol {ROL_ONG} (ONGs dadas de alta desde la app)")


def desplegar_proceso(b: Bonita, bar: Path) -> dict:
    paso("Proceso")
    nombre, version = bar.stem.rsplit("--", 1)
    existentes = b.todos("/API/bpm/process", f=[f"name={nombre}", f"version={version}"])
    if existentes:
        proceso = existentes[0]
        print(f"  ya desplegado (id {proceso['id']}); para redesplegar: --recrear")
    else:
        tmp = b.subir("processUpload", bar)
        proceso = b.pedir("POST", "/API/bpm/process", json={"fileupload": tmp}).json()
        print(f"  desplegado {nombre} {version} (id {proceso['id']})")
    pid = proceso["id"]
    for problema in b.todos("/API/bpm/processResolutionProblem", f=f"process_id={pid}"):
        print(f"  sin resolver: {problema['message']}")
    proceso = b.pedir("GET", f"/API/bpm/process/{pid}").json()
    if proceso["configurationState"] == "RESOLVED" and proceso["activationState"] != "ENABLED":
        b.pedir("PUT", f"/API/bpm/process/{pid}", json={"activationState": "ENABLED"})
        proceso = b.pedir("GET", f"/API/bpm/process/{pid}").json()
    print(f"  configurationState={proceso['configurationState']} activationState={proceso['activationState']}")
    for actor in b.todos("/API/bpm/actor", f=f"process_id={pid}"):
        miembros = b.todos("/API/bpm/actorMember", f=f"actor_id={actor['id']}")
        grupos = [b.pedir("GET", f"/API/identity/group/{m['group_id']}").json()["path"] for m in miembros if m.get("group_id") not in (None, "-1")]
        print(f"  actor «{actor['name']}» → {', '.join(grupos) or '(sin miembros)'}")
    return proceso


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bos", type=Path, default=BOS_POR_DEFECTO, help="el .bos a desplegar (por defecto entrega42_local.bos)")
    parser.add_argument("--imagen", default="bonita:2025.2")
    parser.add_argument("--recrear", action="store_true", help="borra el contenedor `bonita` (y sus casos) antes de empezar")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="bonita-bar-") as trabajo:
        bar, organizacion = construir_bar(args.bos.resolve(), Path(trabajo))
        levantar_contenedor(args.imagen, args.recrear)
        tecnico = Bonita(*TECNICO)
        importar_organizacion(tecnico, organizacion)
        asignar_perfiles(tecnico)
        admin = Bonita("walter.bates", "bpm")  # el usuario técnico no tiene permisos sobre procesos: se despliega como admin
        proceso = desplegar_proceso(admin, bar)

    ok = proceso["activationState"] == "ENABLED" and proceso["configurationState"] == "RESOLVED"
    print(f"\n{'Listo' if ok else 'Quedó a medias'}: {BASE} (walter.bates / bpm) · proceso «{proceso['name']}» v{proceso['version']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
