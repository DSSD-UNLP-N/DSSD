from app.models import (
    Emergencia,
    EstadoEmergencia,
    EstadoOferta,
    Gravedad,
    Lote,
    Municipio,
    Oferta,
    Ong,
)


def test_metricas_locales_agrega_estados_correspondientes(client, seeded, login):
    with seeded() as db:
        municipio = db.query(Municipio).one()
        db.add_all(
            [
                Emergencia(
                    municipio_id=municipio.id,
                    tipo="inundacion",
                    nivel_gravedad=Gravedad.ALTO,
                    zona_afectada="Centro",
                    descripcion="Resuelta",
                    estado=EstadoEmergencia.RESUELTA,
                    lotes=[Lote(recurso="Agua", cantidad=10, unidad="litros")],
                ),
                Emergencia(
                    municipio_id=municipio.id,
                    tipo="incendio",
                    nivel_gravedad=Gravedad.MEDIO,
                    zona_afectada="Norte",
                    descripcion="En ejecución",
                    estado=EstadoEmergencia.EN_EJECUCION,
                    lotes=[Lote(recurso="Raciones", cantidad=20, unidad="raciones")],
                ),
                Emergencia(
                    municipio_id=municipio.id,
                    tipo="terremoto",
                    nivel_gravedad=Gravedad.BAJO,
                    zona_afectada="Sur",
                    descripcion="Registrada",
                    estado=EstadoEmergencia.REGISTRADA,
                    lotes=[Lote(recurso="Mantas", cantidad=100, unidad="unidades")],
                ),
            ]
        )
        db.commit()

    login("auditor")
    response = client.get("/api/metricas/locales")

    assert response.status_code == 200
    assert response.json() == {
        "proyectos_finalizados": 1,
        "suministros_movilizados": 10,
        "porcentaje_consorcios": 0.0,
        "tiempo_promedio_resolucion_horas": 0.0,
    }


def test_metricas_locales_sin_ofertas_devuelve_cero(client, login):
    login("auditor")
    response = client.get("/api/metricas/locales")

    assert response.status_code == 200
    assert response.json()["porcentaje_consorcios"] == 0.0
    assert response.json()["tiempo_promedio_resolucion_horas"] == 0.0


def test_metricas_locales_combina_datos_de_bonita(client, monkeypatch, login):
    class FakeBonita:
        def __init__(self, base_url, timeout):
            pass

        def login(self, username, password):
            pass

        def resolve_process_id(self, name, version):
            return "42"

        def average_archived_case_duration_hours(self, process_definition_id):
            assert process_definition_id == "42"
            return 12.5

    monkeypatch.setattr("app.routers.api.BonitaClient", FakeBonita)

    login("auditor")
    response = client.get("/api/metricas/locales")

    assert response.status_code == 200
    assert response.json()["proyectos_finalizados"] == 0
    assert response.json()["tiempo_promedio_resolucion_horas"] == 12.5


def test_metricas_locales_calcula_porcentaje_de_proyectos_resueltos_con_consorcio(
    client, seeded, login
):
    with seeded() as db:
        municipio = db.query(Municipio).one()
        ongs = db.query(Ong).order_by(Ong.id).all()
        emergencia = Emergencia(
            municipio_id=municipio.id,
            tipo="inundacion",
            nivel_gravedad=Gravedad.ALTO,
            zona_afectada="Centro",
            descripcion="Emergencia con ofertas",
            estado=EstadoEmergencia.EN_EJECUCION,
        )
        db.add(emergencia)
        db.flush()
        emergencia_no_resuelta = Emergencia(
            municipio_id=municipio.id,
            tipo="incendio",
            nivel_gravedad=Gravedad.MEDIO,
            zona_afectada="Norte",
            descripcion="Oferta todavía presentada",
            estado=EstadoEmergencia.EN_EJECUCION,
        )
        db.add(emergencia_no_resuelta)
        db.flush()
        db.add_all(
            [
                Oferta(
                    emergencia_id=emergencia.id,
                    ong_id=ongs[0].id,
                    es_consorcio=False,
                    estado=EstadoOferta.ADJUDICADA,
                ),
                Oferta(
                    emergencia_id=emergencia.id,
                    ong_id=ongs[1].id,
                    es_consorcio=True,
                    estado=EstadoOferta.FINALIZADA,
                ),
                Oferta(
                    emergencia_id=emergencia_no_resuelta.id,
                    ong_id=ongs[0].id,
                    es_consorcio=True,
                    estado=EstadoOferta.PRESENTADA,
                ),
            ]
        )
        db.commit()

    login("auditor")
    response = client.get("/api/metricas/locales")

    assert response.status_code == 200
    assert response.json()["porcentaje_consorcios"] == 50.0
