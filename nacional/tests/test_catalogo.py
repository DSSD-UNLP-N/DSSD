from datetime import date


def test_tipos_recurso_con_su_certificacion(client):
    tipos = {t["codigo"]: t for t in client.get("/tipos-recurso").json()}
    assert tipos["PARAMEDICO"] == {
        "codigo": "PARAMEDICO", "nombre": "Paramédico", "categoria": "PERSONAL",
        "unidad": "personas", "certificacion_requerida": "SALUD_PREHOSP",
    }
    assert tipos["RACION_ALIMENTO"]["certificacion_requerida"] is None


def test_certificaciones_listan_los_recursos_que_habilitan(client):
    certs = {c["codigo"]: c for c in client.get("/certificaciones").json()}
    assert certs["SALUD_PREHOSP"]["tipos_recurso"] == ["AMBULANCIA", "PARAMEDICO"]
    assert certs["RESCATE_URBANO"]["tipos_recurso"] == ["RESCATISTA_URBANO"]


def test_ongs_filtra_por_estado(client):
    todas = client.get("/ongs").json()
    habilitadas = client.get("/ongs", params={"estado": "HABILITADA"}).json()
    assert len(todas) == 3
    assert {o["cuit"] for o in habilitadas} == {"30-54666544-5", "30-68522415-9"}
    assert all(o["estado"] == "HABILITADA" for o in habilitadas)
    assert client.get("/ongs", params={"estado": "NOSE"}).status_code == 422


def test_ficha_de_ong(client):
    ficha = client.get("/ongs/30-54666544-5").json()
    assert ficha["nombre"] == "Cruz Roja Argentina"
    assert [c["codigo"] for c in ficha["certificaciones"]] == ["SALUD_PREHOSP"]
    assert ficha["certificaciones"][0]["riesgo_max"] == "MEDIO"
    assert ficha["certificaciones"][0]["vigente"] is True
    inv = {i["tipo_recurso"]: i for i in ficha["inventario"]}
    assert inv["PARAMEDICO"]["disponible"] == 4
    assert inv["PARAMEDICO"]["riesgo_permitido"] == "MEDIO"
    assert inv["RACION_ALIMENTO"]["riesgo_permitido"] == "CRITICO"  # insumo: sin certificación requerida


def test_ficha_marca_la_certificacion_vencida_y_no_da_riesgo_permitido(client):
    ficha = client.get("/ongs/30-68522415-9").json()
    cert = next(c for c in ficha["certificaciones"] if c["codigo"] == "SALUD_PREHOSP")
    assert cert["vigente"] is False and cert["vence_el"] < date.today().isoformat()
    inv = {i["tipo_recurso"]: i for i in ficha["inventario"]}
    assert inv["PARAMEDICO"]["riesgo_permitido"] is None
    assert inv["BOTE_RESCATE"]["riesgo_permitido"] == "CRITICO"


def test_ficha_de_ong_inexistente_da_404(client):
    assert client.get("/ongs/00-0-0").status_code == 404


def test_disponibilidad_suma_solo_ongs_habilitadas(client):
    d = {x["tipo_recurso"]: x for x in client.get("/recursos/disponibilidad").json()}
    # 4 de Cruz Roja + 6 de Bomberos; la suspendida no tiene paramédicos.
    assert d["PARAMEDICO"]["disponible"] == 10
    assert {o["cuit"] for o in d["PARAMEDICO"]["por_ong"]} == {"30-54666544-5", "30-68522415-9"}
    # Raciones: la ONG suspendida (800) no cuenta.
    assert d["RACION_ALIMENTO"]["cantidad_total"] == 5000


def test_disponibilidad_descuenta_lo_comprometido(client, session_factory):
    from sqlalchemy import select

    from app.models import Inventario, TipoRecurso

    with session_factory() as db:
        tipo = db.scalar(select(TipoRecurso).where(TipoRecurso.codigo == "PARAMEDICO"))
        inv = db.scalars(select(Inventario).where(Inventario.tipo_recurso_id == tipo.id)).first()
        inv.cantidad_comprometida = inv.cantidad_total
        db.commit()
    (fila,) = client.get("/recursos/disponibilidad", params={"tipo_recurso": "PARAMEDICO"}).json()
    assert fila["cantidad_comprometida"] > 0
    assert fila["disponible"] == fila["cantidad_total"] - fila["cantidad_comprometida"]


def test_disponibilidad_de_tipo_inexistente_da_404(client):
    assert client.get("/recursos/disponibilidad", params={"tipo_recurso": "NADA"}).status_code == 404
