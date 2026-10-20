"""Evaluación transitoria: contrato T34, perfiles por dueño y snapshot coherente."""

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from soporte_nacional import auth, cuenta_ong, datos
from sqlalchemy import Connection, Engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_database_models import DatosNacionales, crear_compromiso, crear_datos

from app.db import session as db_module
from app.db.models import (
    Compromiso,
    EstadoOng,
    NivelRiesgo,
    OperacionIdempotente,
    Proyecto,
    Recurso,
)
from app.db.session import get_db_evaluacion
from app.main import app
from app.schemas.validaciones import (
    ParticipanteSnapshot,
    ValidacionRequest,
)
from app.services.validaciones import validar_snapshot

__all__ = ["datos"]
RUTA = "/api/v1/validaciones"
FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_t34.json"


def snapshot(datos: DatosNacionales) -> ValidacionRequest:
    """Adapta únicamente mappings explícitos de una fixture del contrato T34."""
    s = ValidacionRequest.model_validate_json(FIXTURE.read_text())
    s.sistema_origen = datos.origen.codigo
    lote = s.lotes[0]
    lote.capacidad_nacional_id = datos.capacidad.id
    lote.codigo_capacidad = datos.capacidad.codigo
    lote.unidad = datos.capacidad.unidad
    oferta = s.ofertas[0]
    oferta.ong_nacional_id = datos.ong.id
    oferta.participantes[0].ong_nacional_id = datos.ong.id
    oferta.items[0].unidad = datos.capacidad.unidad
    aporte = oferta.items[0].aportes[0]
    aporte.ong_nacional_id = datos.ong.id
    aporte.recurso_nacional_id = datos.recurso.id
    aporte.capacidad_nacional_id = datos.capacidad.id
    aporte.unidad = datos.capacidad.unidad
    return s


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def database() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db_evaluacion] = database
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()


@pytest.mark.parametrize("riesgo", list(NivelRiesgo))
def test_riesgo_y_vigencia_no_limitan_aportes(
    client: TestClient,
    datos: DatosNacionales,
    riesgo: NivelRiesgo,
) -> None:
    s = snapshot(datos)
    s.gravedad = NivelRiesgo.CRITICA
    s.lotes[0].riesgo_requerido = riesgo
    response = client.post(
        RUTA,
        headers=auth(datos.integracion),
        json=s.model_dump(mode="json", by_alias=True),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contratoVersion"] == 3
    aporte = body["aportes"][0]
    assert "clasificacion" not in aporte and "nivelesRiesgoPermitidos" not in aporte
    assert (
        aporte["perfilCompetencia"]["capacidadesDeclaradas"][0]["cantidadTotal"]
        == "10.000"
    )
    assert aporte["cantidadDisponibleConsultada"] == "10.000"
    assert aporte["motivos"] == []


def test_no_reserva_y_stock_insuficiente_conserva_competencia(
    session: Session, datos: DatosNacionales
) -> None:
    crear_compromiso(session, datos, cantidad=Decimal(8))
    session.commit()
    inicial = [
        session.scalar(select(func.count()).select_from(t))
        for t in (Proyecto, Compromiso, OperacionIdempotente)
    ]
    sentencias: list[str] = []

    def registrar(
        _conn: Connection,
        _cursor: object,
        sql: str,
        _params: object,
        _context: object,
        _many: bool,
    ) -> None:
        sentencias.append(sql)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", registrar)
    try:
        respuesta = validar_snapshot(session, snapshot(datos))
    finally:
        event.remove(connection, "before_cursor_execute", registrar)
    p = respuesta.aportes[0]
    assert p.cantidad_disponible_consultada == Decimal(2)
    assert "DISPONIBILIDAD_INSUFICIENTE" in {m.codigo for m in p.motivos}
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in sentencias)
    assert inicial == [
        session.scalar(select(func.count()).select_from(t))
        for t in (Proyecto, Compromiso, OperacionIdempotente)
    ]
    assert datos.recurso.cantidad_total == Decimal(10)


@pytest.mark.parametrize(
    "estado", [EstadoOng.PENDIENTE, EstadoOng.SUSPENDIDA, EstadoOng.BAJA]
)
def test_institucion_no_habilitada_no_aporta(
    session: Session, datos: DatosNacionales, estado: EstadoOng
) -> None:
    datos.ong.estado = estado
    session.commit()
    p = validar_snapshot(session, snapshot(datos)).aportes[0]
    assert "ONG_NO_HABILITADA" in {m.codigo for m in p.motivos}


def test_consorcio_evalua_a_cada_dueno(
    session: Session, datos: DatosNacionales
) -> None:
    otra = crear_datos(session, f"miembro-{uuid4().hex}")
    r = Recurso(
        ong_id=otra.ong.id,
        capacidad_id=datos.capacidad.id,
        codigo_interno="propio",
        nombre="Propio",
        cantidad_total=Decimal(10),
    )
    session.add(r)
    session.commit()
    s = snapshot(datos)
    oferta = s.ofertas[0]
    oferta.participantes.append(
        ParticipanteSnapshot(ong_id=2, ong_nacional_id=otra.ong.id, rol="MIEMBRO")
    )
    aporte = oferta.items[0].aportes[0].model_copy(deep=True)
    aporte.aporte_id = 51
    aporte.ong_id = 2
    aporte.ong_nacional_id = otra.ong.id
    aporte.recurso_nacional_id = r.id
    oferta.items[0].aportes.append(aporte)
    oferta.items[0].cantidad_ofrecida_exacta = Decimal(12)
    resultado = validar_snapshot(session, s)
    assert all(not p.motivos for p in resultado.aportes)
    assert resultado.aportes[1].perfil_competencia.ong_id == otra.ong.id


@pytest.mark.parametrize(
    "tipo", ["ong", "recurso", "capacidad", "unidad", "fraccion", "legacy"]
)
def test_referencias_incompletas_y_aportes_incompatibles(
    client: TestClient, datos: DatosNacionales, tipo: str
) -> None:
    s = snapshot(datos)
    aporte = s.ofertas[0].items[0].aportes[0]
    if tipo == "ong":
        s.ofertas[0].ong_nacional_id = None
        s.ofertas[0].participantes[0].ong_nacional_id = None
        aporte.ong_nacional_id = None
    elif tipo == "recurso":
        aporte.recurso_nacional_id = uuid4()
    elif tipo == "capacidad":
        s.lotes[0].capacidad_nacional_id = None
    elif tipo == "unidad":
        aporte.unidad = "kg"
    elif tipo == "fraccion":
        aporte.cantidad = Decimal("1.125")
        s.ofertas[0].items[0].cantidad_ofrecida_exacta = aporte.cantidad
    elif tipo == "legacy":
        s.ofertas[0].items[0].aportes = []
        s.ofertas[0].participantes = []
        s.ofertas[0].ong_nacional_id = None
    else:
        s.gravedad = None
    response = client.post(
        RUTA, headers=auth(datos.admin), json=s.model_dump(mode="json", by_alias=True)
    )
    assert response.status_code == 200, response.text
    assert response.json()["aportes"][0]["motivos"]


def test_ronda_vacia_y_stock_repetido(session: Session, datos: DatosNacionales) -> None:
    s = snapshot(datos)
    otra = s.ofertas[0].model_copy(deep=True)
    otra.oferta_id = 31
    otra.items[0].item_id = 42
    otra.items[0].aportes[0].aporte_id = 51
    s.ofertas.append(otra)
    respuesta = validar_snapshot(session, s)
    assert len(respuesta.aportes) == 2 and len(respuesta.recursos_consultados) == 1
    assert respuesta.recursos_consultados[0].cantidad_solicitada_snapshot == Decimal(12)
    assert respuesta.recursos_consultados[0].cantidad_disponible == Decimal(10)
    s.ofertas = []
    respuesta = validar_snapshot(session, s)
    assert respuesta.aportes == [] and respuesta.recursos_consultados == []


@pytest.mark.parametrize("tipo", ["ajeno", "inactivo", "capacidad_inactiva"])
def test_propiedad_actividad_y_revocacion(
    session: Session, datos: DatosNacionales, tipo: str
) -> None:
    s = snapshot(datos)
    if tipo == "ajeno":
        otra = crear_datos(session, f"ajena-{uuid4().hex}")
        s.ofertas[0].items[0].aportes[0].recurso_nacional_id = otra.recurso.id
    elif tipo == "inactivo":
        datos.recurso.activo = False
    elif tipo == "capacidad_inactiva":
        datos.capacidad.activa = False
    session.commit()
    p = validar_snapshot(session, s).aportes[0]
    codigo = {
        "ajeno": "RECURSO_AJENO",
        "inactivo": "RECURSO_INACTIVO",
        "capacidad_inactiva": "CAPACIDAD_INACTIVA",
    }[tipo]
    assert codigo in {m.codigo for m in p.motivos}


def test_historial_de_acreditaciones_no_condiciona_la_evaluacion(
    session: Session, datos: DatosNacionales
) -> None:
    s = snapshot(datos)
    for instante in [
        datos.acreditacion.vigente_desde - timedelta(days=1),
        datos.acreditacion.vigente_hasta,
    ]:
        p = validar_snapshot(session, s, ahora=instante).aportes[0]
        assert p.motivos == []
        assert p.perfil_competencia is not None


def test_seguridad_y_contrato_malformado(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    s = snapshot(datos)
    body = s.model_dump(mode="json", by_alias=True)
    assert client.post(RUTA, json=body).status_code == 401
    ong = cuenta_ong(session, datos)
    assert client.post(RUTA, headers=auth(ong), json=body).status_code == 403
    s.sistema_origen = "ajeno"
    assert (
        client.post(
            RUTA,
            headers=auth(datos.integracion),
            json=s.model_dump(mode="json", by_alias=True),
        ).status_code
        == 403
    )
    assert (
        client.post(
            RUTA,
            headers=auth(datos.admin),
            json=s.model_dump(mode="json", by_alias=True),
        ).status_code
        == 404
    )
    s = snapshot(datos)
    s.ofertas[0].items[0].aportes[0].cantidad = Decimal("7")
    assert (
        client.post(
            RUTA,
            headers=auth(datos.admin),
            json=s.model_dump(mode="json", by_alias=True),
        ).status_code
        == 422
    )
    datos.integracion.activa = False
    session.commit()
    assert (
        client.post(RUTA, headers=auth(datos.integracion), json=body).status_code == 401
    )


def test_snapshot_real_solo_lectura_y_escritura_concurrente(
    engine_migrado: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(engine_migrado) as writer:
        d = crear_datos(writer, f"snapshot-{uuid4().hex}")
        s = snapshot(d)
        recurso_id = d.recurso.id
        writer.commit()
    monkeypatch.setattr(db_module, "engine", engine_migrado)
    database = get_db_evaluacion()
    reader = next(database)
    try:
        assert reader.scalar(text("SHOW transaction_read_only")) == "on"
        assert reader.get(Recurso, recurso_id).cantidad_total == Decimal(10)
        with Session(engine_migrado) as writer:
            writer.get(Recurso, recurso_id).cantidad_total = Decimal(0)
            writer.commit()
        resultado = validar_snapshot(reader, s)
        assert resultado.aportes[0].cantidad_disponible_consultada == Decimal(10)
        with pytest.raises(DBAPIError):
            reader.execute(
                text("UPDATE recurso SET cantidad_total = 1 WHERE id = :id"),
                {"id": recurso_id},
            )
        reader.rollback()
    finally:
        database.close()
    with Session(engine_migrado) as reader:
        assert validar_snapshot(reader, s).aportes[
            0
        ].cantidad_disponible_consultada == Decimal(0)
