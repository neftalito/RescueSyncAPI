"""Directorio, filtros de competencia y lectura sin efectos sobre inventario."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, event
from sqlalchemy.orm import Session
from test_certificaciones import auth, client, cuenta_ong, datos
from test_database_models import DatosNacionales

from app.db.models import Capacidad, EstadoOng, NivelRiesgo, Ong, TipoRecurso
from app.schemas.certificaciones import (
    AcreditacionCreate,
    AlcanceCreate,
    CertificacionCreate,
    RevocacionRequest,
)
from app.services.certificaciones import (
    otorgar_acreditacion,
    publicar_certificacion,
    revocar_acreditacion,
)
from app.services.ongs import listar_ongs_habilitadas

__all__ = ["client", "datos"]
RUTA = "/api/v1/ongs/habilitadas"


@pytest.mark.parametrize("estado", list(EstadoOng))
def test_directorio_separa_institucion_y_competencia(
    client: TestClient, session: Session, datos: DatosNacionales, estado: EstadoOng
) -> None:
    datos.ong.estado = estado
    session.commit()
    respuesta = client.get(RUTA, headers=auth(datos.admin))
    assert respuesta.status_code == 200
    ongs = respuesta.json()["ongs"]
    assert len(ongs) == (1 if estado == EstadoOng.HABILITADA else 0)
    if ongs:
        assert ongs[0]["ongId"] == str(datos.ong.id)
        assert ongs[0]["capacidadesHabilitadas"][0]["riesgoMaximo"] == "ALTA"
        assert set(ongs[0]) == {
            "ongId",
            "nombre",
            "estadoOng",
            "capacidadesHabilitadas",
            "motivosPerfil",
        }
    assert respuesta.headers["cache-control"] == "no-store"


def test_perfil_vacio_conserva_institucion_sin_filtros(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    revocar_acreditacion(
        session,
        datos.admin.id,
        RevocacionRequest(
            ong_id=datos.ong.id,
            acreditacion_id=datos.acreditacion.id,
            motivo="Renovación",
        ),
    )
    otorgar_acreditacion(
        session,
        datos.admin.id,
        AcreditacionCreate(
            ong_id=datos.ong.id,
            certificacion_id=datos.certificacion.id,
            emisor="Autoridad",
            numero_credencial="vencida",
            vigente_desde=datetime.now(UTC) - timedelta(days=2),
            vigente_hasta=datetime.now(UTC) - timedelta(days=1),
        ),
    )
    session.commit()
    ong = client.get(RUTA, headers=auth(datos.integracion)).json()["ongs"][0]
    assert ong["capacidadesHabilitadas"] == []
    assert ong["motivosPerfil"][0]["codigo"] == "SIN_COMPETENCIAS_VIGENTES"
    for params in ({"capacidadId": str(datos.capacidad.id)}, {"nivelRiesgo": "BAJA"}):
        assert (
            client.get(RUTA, headers=auth(datos.admin), params=params).json()["ongs"]
            == []
        )


def test_filtros_coinciden_en_la_misma_capacidad_y_conservan_perfil(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    segunda = Capacidad(
        codigo=f"AGUA-{uuid4()}",
        nombre="Agua",
        tipo=TipoRecurso.SUMINISTRO,
        unidad="litros",
        admite_fracciones=True,
    )
    session.add(segunda)
    session.flush()
    revision = publicar_certificacion(
        session,
        datos.admin.id,
        CertificacionCreate(
            codigo="DOS",
            revision=1,
            nombre="Dos capacidades",
            alcances=[
                AlcanceCreate(
                    capacidad_id=datos.capacidad.id, riesgo_maximo=NivelRiesgo.BAJA
                ),
                AlcanceCreate(
                    capacidad_id=segunda.id, riesgo_maximo=NivelRiesgo.CRITICA
                ),
            ],
        ),
    )
    otorgar_acreditacion(
        session,
        datos.admin.id,
        AcreditacionCreate(
            ong_id=datos.ong.id,
            certificacion_id=revision,
            emisor="Autoridad",
            numero_credencial="dos",
            vigente_desde=datetime.now(UTC) - timedelta(days=1),
            vigente_hasta=datetime.now(UTC) + timedelta(days=1),
        ),
    )
    session.commit()
    assert (
        client.get(
            RUTA,
            headers=auth(datos.admin),
            params={"capacidadId": str(datos.capacidad.id), "nivelRiesgo": "CRITICA"},
        ).json()["ongs"]
        == []
    )
    ongs = client.get(
        RUTA,
        headers=auth(datos.admin),
        params={"capacidadId": str(segunda.id), "nivelRiesgo": "CRITICA"},
    ).json()["ongs"]
    assert len(ongs) == 1 and len(ongs[0]["capacidadesHabilitadas"]) == 2
    assert client.get(
        RUTA, headers=auth(datos.admin), params={"nivelRiesgo": "CRITICA"}
    ).json()["ongs"]
    assert (
        client.get(
            RUTA, headers=auth(datos.admin), params={"capacidadId": str(uuid4())}
        ).json()["ongs"]
        == []
    )


@pytest.mark.parametrize(
    "cambio", ["futura", "vencida", "revocada", "revision", "capacidad"]
)
def test_competencia_invalida_no_aporta(
    session: Session, datos: DatosNacionales, cambio: str
) -> None:
    ahora = datetime.now(UTC)
    if cambio == "futura":
        ahora = datos.acreditacion.vigente_desde - timedelta(seconds=1)
    elif cambio == "vencida":
        ahora = datos.acreditacion.vigente_hasta
    elif cambio == "revocada":
        revocar_acreditacion(
            session,
            datos.admin.id,
            RevocacionRequest(
                ong_id=datos.ong.id,
                acreditacion_id=datos.acreditacion.id,
                motivo="Prueba",
            ),
        )
    elif cambio == "revision":
        datos.certificacion.activa = False
    else:
        datos.capacidad.activa = False
    session.commit()
    perfil = listar_ongs_habilitadas(session, ahora=ahora)
    assert perfil.evaluado_en == ahora
    assert len(perfil.ongs) == 1 and not perfil.ongs[0].capacidades_habilitadas
    assert not listar_ongs_habilitadas(
        session, ahora=ahora, nivel_riesgo=NivelRiesgo.BAJA
    ).ongs


def test_inicio_inclusivo_y_stock_independiente(
    session: Session, datos: DatosNacionales
) -> None:
    ahora = datos.acreditacion.vigente_desde
    datos.recurso.activo = False
    session.commit()
    assert listar_ongs_habilitadas(session, ahora=ahora).ongs[0].capacidades_habilitadas


def test_lectura_en_conjunto_incluye_ong_sin_historia_y_no_escribe(
    session: Session, datos: DatosNacionales
) -> None:
    session.add(
        Ong(
            identificador_institucional=f"otra:{uuid4()}",
            nombre="A sin competencias",
            email_contacto="privado@example.test",
            estado=EstadoOng.HABILITADA,
            habilitada_en=datetime.now(UTC),
            habilitada_por_id=datos.admin.id,
        )
    )
    session.commit()
    sentencias: list[str] = []

    def registrar(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        sentencias.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", registrar)
    try:
        directorio = listar_ongs_habilitadas(session)
    finally:
        event.remove(bind, "before_cursor_execute", registrar)
    consultas = [s for s in sentencias if s.lstrip().upper().startswith("SELECT")]
    assert len(consultas) == 1
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for s in sentencias
    )
    assert [ong.nombre for ong in directorio.ongs] == [
        "A sin competencias",
        "ONG de prueba",
    ]
    assert not directorio.ongs[0].capacidades_habilitadas
    assert not session.new and not session.dirty and not session.deleted


def test_acceso_global_resumido_no_amplia_historia_privada(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    usuario = cuenta_ong(session, datos)
    assert client.get(RUTA, headers=auth(usuario)).status_code == 200
    assert (
        client.get(
            f"/api/v1/ongs/{uuid4()}/certificaciones", headers=auth(usuario)
        ).status_code
        == 403
    )
    for headers in ({}, {"Authorization": "Bearer invalido"}):
        assert client.get(RUTA, headers=headers).status_code == 401
    usuario.activa = False
    session.commit()
    assert client.get(RUTA, headers=auth(usuario)).status_code == 401
    datos.origen.activo = False
    session.commit()
    assert client.get(RUTA, headers=auth(datos.integracion)).status_code == 403


@pytest.mark.parametrize(
    "params", [{"capacidadId": "incorrecto"}, {"nivelRiesgo": "MAXIMO"}]
)
def test_filtros_invalidos_y_openapi(
    client: TestClient, datos: DatosNacionales, params: dict[str, str]
) -> None:
    assert client.get(RUTA, headers=auth(datos.admin), params=params).status_code == 422
    assert client.get("/openapi.json").json()["paths"][RUTA]["get"]["security"] == [
        {"HTTPBearer": []}
    ]
