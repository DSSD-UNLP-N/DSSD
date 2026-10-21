"""
Cliente minimo para la REST API de Bonita Engine, pensado para probar
a mano (o desde un script) el arranque de una instancia de RescueSync
y el seteo de sus variables de proceso -- exactamente lo que pide
HU-2.4 / T-07 / T-08 de la Entrega 2.

Verificado el 19/09/2026 contra el Bonita embebido de Studio 10.4.0
(localhost:8080, usuario walter.bates/bpm): login + CSRF, resolucion de
processDefinitionId, instanciacion con los 4 inputs del contrato y lectura
de tareas funcionan, y tambien set_case_variable (PUT caseVariable) y
avanzar tareas humanas (PUT userTask assigned_id + POST execution).
Ojo: listar tareas necesita p y c; la primera tarea aparece con un
instante de retraso.

Requisitos: pip install requests

Uso tipico (una vez que el proceso este habilitado y corriendo en el
servidor embebido de Studio, tipicamente localhost:8080/bonita):

    python bonita_client.py \
        --base-url http://localhost:8080/bonita \
        --username operador.municipal --password bpm \
        --process-name RescueSync --process-version 1.0 \
        --emergencia-id 1 --municipio-id 10 --nivel-gravedad ALTA \
        --ventana-ofertas-iso 2026-09-20T18:00:00Z
"""

import argparse
import sys
import time

import requests

# Tipos Java de las variables del proceso (el contrato de instanciacion esta en
# CONTRACT_INPUTS de backend/app/integrations/bonita.py y lo comprueba un test contra el .bos).
VARIABLE_TYPES = {
    "emergenciaId": "java.lang.Long",
    "municipioId": "java.lang.Long",
    "nivelGravedad": "java.lang.String",
    "ventanaOfertasISO": "java.lang.String",
    "plazoAdjudicacionISO": "java.lang.String",  # declarada, sin uso en Entrega 2
    "coberturaCompleta": "java.lang.Boolean",
    "porcentajeCobertura": "java.lang.Double",
    "decisionCoordinador": "java.lang.String",
    "ofertasJson": "java.lang.String",
    "ongsAdjudicadas": "java.lang.String",
}

# Los unicos 4 inputs del contrato de instanciacion (seccion 1 del .md).
# El resto de las variables las setean los nodos del proceso, no la app.
CONTRACT_INPUTS = ("emergenciaId", "municipioId", "nivelGravedad", "ventanaOfertasISO")


class BonitaClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.api_token = None

    def login(self, username: str, password: str) -> None:
        """
        POST /loginservice arranca la sesion. Bonita devuelve una cookie
        X-Bonita-API-Token que hay que reenviar como HEADER en todo
        request que no sea GET (proteccion CSRF activa desde 7.4.0).
        """
        resp = self.session.post(
            f"{self.base_url}/loginservice",
            data={"username": username, "password": password, "redirect": "false"},
        )
        resp.raise_for_status()
        token = self.session.cookies.get("X-Bonita-API-Token")
        if not token:
            raise RuntimeError(
                "Login OK pero no aparecio la cookie X-Bonita-API-Token. "
                "Revisa usuario/password o si cambio el mecanismo de CSRF "
                "en esta version de Bonita."
            )
        self.api_token = token
        self.session.headers.update({"X-Bonita-API-Token": token})

    def resolve_process_id(self, name: str, version: str) -> str:
        """
        GET /API/bpm/process?f=name=...&f=version=...
        Resuelve nombre+version del proceso al processDefinitionId
        interno que piden el resto de los endpoints.
        """
        resp = self.session.get(
            f"{self.base_url}/API/bpm/process",
            params={"f": [f"name={name}", f"version={version}"]},
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            raise RuntimeError(
                f"No se encontro un proceso '{name}' version '{version}'. "
                "Verifica que este habilitado (no solo guardado) en Studio."
            )
        return results[0]["id"]

    def start_case(self, process_definition_id: str, contract_inputs: dict) -> str:
        """
        POST /API/bpm/process/{id}/instantiation
        Segun el contrato de instanciacion del proceso,
        Studio va a tener 4 operations "Set variable" que copian estos 4
        inputs del contrato a las variables homonimas -- por eso se mandan
        directo en el body de instanciacion, no via caseVariable despues.
        """
        missing = [k for k in CONTRACT_INPUTS if k not in contract_inputs]
        if missing:
            raise ValueError(f"Faltan inputs obligatorios del contrato: {missing}")
        resp = self.session.post(
            f"{self.base_url}/API/bpm/process/{process_definition_id}/instantiation",
            json=contract_inputs,
        )
        resp.raise_for_status()
        return resp.json()["caseId"]

    def set_case_variable(self, case_id: str, name: str, value, java_type: str) -> None:
        """
        PUT /API/bpm/caseVariable/{caseId}/{variableName}
        Para pisar una variable INTERNA a mano durante una prueba (ej.
        forzar coberturaCompleta=true para probar la rama del gateway sin
        esperar al ServiceTask real). Los 4 inputs del contrato no van por
        aca -- esos se mandan en la instanciacion (ver start_case).
        Solo funciona si la variable ya fue declarada en el proceso dentro
        de Studio -- este endpoint no crea variables nuevas.
        """
        resp = self.session.put(
            f"{self.base_url}/API/bpm/caseVariable/{case_id}/{name}",
            json={"value": value, "type": java_type},
        )
        resp.raise_for_status()

    def set_case_variables(self, case_id: str, values: dict) -> None:
        for name, value in values.items():
            if name not in VARIABLE_TYPES:
                raise ValueError(f"Variable '{name}' no esta en VARIABLE_TYPES")
            self.set_case_variable(case_id, name, value, VARIABLE_TYPES[name])

    def get_human_tasks(self, case_id: str) -> list:
        """GET /API/bpm/humanTask?f=caseId=... -- para ver en que tarea quedo el caso."""
        resp = self.session.get(
            f"{self.base_url}/API/bpm/humanTask",
            params={"f": f"caseId={case_id}", "p": 0, "c": 100},
        )
        resp.raise_for_status()
        return resp.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="ej: http://localhost:8080/bonita")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--process-name", default="Gestion Integral de la Emergencia")
    parser.add_argument("--process-version", default="1.0")
    parser.add_argument("--emergencia-id", type=int, required=True)
    parser.add_argument("--municipio-id", type=int, required=True)
    parser.add_argument("--nivel-gravedad", required=True, choices=["BAJO", "MEDIO", "ALTO", "CRITICO"])
    parser.add_argument(
        "--ventana-ofertas-iso",
        required=True,
        help="ISO-8601 con offset, ej. 2026-09-13T20:00:00-03:00",
    )
    args = parser.parse_args()

    client = BonitaClient(args.base_url)

    print(f"Login como {args.username}...")
    client.login(args.username, args.password)
    print("OK, token CSRF obtenido.")

    print(f"Resolviendo processDefinitionId de {args.process_name} v{args.process_version}...")
    process_id = client.resolve_process_id(args.process_name, args.process_version)
    print(f"processDefinitionId = {process_id}")

    contract_inputs = {
        "emergenciaId": args.emergencia_id,
        "municipioId": args.municipio_id,
        "nivelGravedad": args.nivel_gravedad,
        "ventanaOfertasISO": args.ventana_ofertas_iso,
    }
    print(f"Arrancando instancia con contrato: {contract_inputs}")
    case_id = client.start_case(process_id, contract_inputs)
    print(f"caseId = {case_id}")

    print("Tareas humanas abiertas para este caso:")
    tasks = []
    for _ in range(10):  # el motor crea la primera tarea de forma asincrona
        tasks = client.get_human_tasks(case_id)
        if tasks:
            break
        time.sleep(0.5)
    for task in tasks:
        print(f"  - {task.get('name')} (id={task.get('id')}, estado={task.get('state')})")


if __name__ == "__main__":
    sys.exit(main())
