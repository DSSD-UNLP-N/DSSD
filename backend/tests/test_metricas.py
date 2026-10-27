from app.models import Emergencia, EstadoEmergencia, Gravedad, Lote, Municipio


def test_metricas_locales_agrega_estados_correspondientes(client, seeded):
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

    response = client.get("/api/metricas/locales")

    assert response.status_code == 200
    assert response.json() == {
        "proyectos_finalizados": 1,
        "suministros_movilizados": 30,
        "porcentaje_consorcios": 0.0,
    }
