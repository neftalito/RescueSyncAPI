"""Agregación exacta, población elegible y cambios confirmados entre conexiones."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from test_certificaciones import auth, client, cuenta_ong, datos
from test_database_models import DatosNacionales, crear_compromiso, crear_datos

from app.db.models import (
    Capacidad,
    EstadoCompromiso,
    EstadoOng,
    Ong,
    Recurso,
    TipoRecurso,
)
from app.schemas.inventario import RecursoUpdate
from app.services.disponibilidad import consultar_disponibilidad
from app.services.inventario import InventarioConflictivoError, actualizar_recurso

__all__ = ["client", "datos"]
RUTA = "/api/v1/recursos/disponibilidad"


def test_agrega_sin_multiplicar_stock_y_separa_capacidades(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    crear_compromiso(session, datos, cantidad=Decimal(2))
    crear_compromiso(session, datos, cantidad=Decimal(3))
    otra = Ong(
        identificador_institucional=f"otra:{uuid4()}",
        nombre="Otra ONG",
        email_contacto="privado@example.test",
        estado=EstadoOng.HABILITADA,
        habilitada_en=datetime.now(UTC),
        habilitada_por_id=datos.admin.id,
    )
    capacidad = Capacidad(
        codigo=f"OTRA-{uuid4()}",
        nombre="Otra capacidad",
        unidad=datos.capacidad.unidad,
        tipo=TipoRecurso.PERSONAL,
        admite_fracciones=False,
    )
    session.add_all([otra, capacidad])
    session.flush()
    for ong_id, capacidad_id, cantidad, codigo in (
        (datos.ong.id, datos.capacidad.id, 5, "extra"),
        (otra.id, datos.capacidad.id, 7, "otra"),
        (otra.id, capacidad.id, 9, "distinta"),
    ):
        session.add(
            Recurso(
                ong_id=ong_id,
                capacidad_id=capacidad_id,
                nombre=codigo,
                codigo_interno=codigo,
                cantidad_total=Decimal(cantidad),
            )
        )
    session.commit()
    response = client.get(RUTA, headers=auth(datos.integracion))
    assert (
        response.status_code == 200 and response.headers["cache-control"] == "no-store"
    )
    grupos = response.json()["recursos"]
    assert len(grupos) == 2
    grupo = next(g for g in grupos if g["capacidadId"] == str(datos.capacidad.id))
    assert grupo["cantidadTotal"] == "22.000"
    assert grupo["cantidadComprometida"] == "5.000"
    assert grupo["cantidadDisponible"] == "17.000"
    assert sum(Decimal(o["cantidadDisponible"]) for o in grupo["ongs"]) == Decimal(17)
    assert all(
        set(o)
        == {
            "ongId",
            "nombre",
            "estadoOng",
            "cantidadTotal",
            "cantidadComprometida",
            "cantidadDisponible",
        }
        for o in grupo["ongs"]
    )
    filtrado = client.get(
        RUTA,
        headers=auth(datos.admin),
        params={"ongId": str(otra.id), "capacidadId": str(datos.capacidad.id)},
    ).json()["recursos"]
    assert len(filtrado) == 1 and filtrado[0]["cantidadTotal"] == "7.000"


def test_compromiso_liberacion_repetida_y_edicion_coherentes(
    session: Session, datos: DatosNacionales
) -> None:
    compromiso = crear_compromiso(session, datos, cantidad=Decimal(10))
    session.commit()
    assert consultar_disponibilidad(session).recursos[0].cantidad_disponible == Decimal(
        0
    )
    version = datos.recurso.actualizado_en
    with pytest.raises(InventarioConflictivoError):
        actualizar_recurso(
            session,
            datos.ong.id,
            datos.recurso.id,
            RecursoUpdate(cantidad_total=Decimal(9), actualizado_en=version),
        )
    session.rollback()
    assert consultar_disponibilidad(session).recursos[0].cantidad_disponible == Decimal(
        0
    )
    integracion_id = datos.integracion.id
    compromiso.estado = EstadoCompromiso.LIBERADO
    compromiso.liberado_en = datetime.now(UTC)
    compromiso.liberado_por_id = integracion_id
    session.commit()
    for _ in range(2):
        assert consultar_disponibilidad(session).recursos[
            0
        ].cantidad_disponible == Decimal(10)
    actualizar_recurso(
        session,
        datos.ong.id,
        datos.recurso.id,
        RecursoUpdate(cantidad_total=Decimal(12), actualizado_en=version),
    )
    assert consultar_disponibilidad(session).recursos[0].cantidad_disponible == Decimal(
        12
    )


@pytest.mark.parametrize("estado", list(EstadoOng))
def test_poblacion_institucional_sin_exigir_certificacion(
    session: Session, datos: DatosNacionales, estado: EstadoOng
) -> None:
    datos.ong.estado = estado
    datos.certificacion.activa = False
    session.commit()
    assert bool(consultar_disponibilidad(session).recursos) == (
        estado == EstadoOng.HABILITADA
    )


@pytest.mark.parametrize("campo", ["recurso", "capacidad"])
def test_flags_inactivos_excluyen_stock(
    session: Session, datos: DatosNacionales, campo: str
) -> None:
    if campo == "recurso":
        datos.recurso.activo = False
    else:
        datos.capacidad.activa = False
    session.commit()
    assert not consultar_disponibilidad(session).recursos


def test_fracciones_y_sumas_superiores_al_limite_por_fila(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    capacidad = Capacidad(
        codigo=f"AGUA-{uuid4()}",
        nombre="Agua",
        unidad="litros",
        tipo=TipoRecurso.SUMINISTRO,
        admite_fracciones=True,
    )
    session.add(capacidad)
    session.flush()
    for numero, cantidad in enumerate(("99999999999.999", "0.002")):
        session.add(
            Recurso(
                ong_id=datos.ong.id,
                capacidad_id=capacidad.id,
                nombre="Agua",
                codigo_interno=f"agua-{numero}",
                cantidad_total=Decimal(cantidad),
            )
        )
    session.commit()
    grupo = client.get(
        RUTA, headers=auth(datos.admin), params={"capacidadId": str(capacidad.id)}
    ).json()["recursos"][0]
    assert grupo["cantidadTotal"] == "100000000000.001"
    assert grupo["cantidadDisponible"] == grupo["cantidadTotal"]
    assert grupo["cantidadComprometida"] == "0.000"


def test_lectura_independiente_observa_commit_rollback_y_liberacion(
    engine_migrado: Engine,
) -> None:
    with Session(engine_migrado, expire_on_commit=False) as preparacion:
        datos = crear_datos(preparacion, f"lectura-{uuid4().hex}")
        preparacion.commit()
    with Session(engine_migrado) as escritura, Session(engine_migrado) as lectura:
        crear_compromiso(escritura, datos, cantidad=Decimal(3))

        def disponible() -> Decimal:
            grupo = consultar_disponibilidad(
                lectura, capacidad_id=datos.capacidad.id
            ).recursos[0]
            assert grupo.cantidad_disponible == sum(
                o.cantidad_disponible for o in grupo.ongs
            )
            assert (
                grupo.cantidad_total - grupo.cantidad_comprometida
                == grupo.cantidad_disponible
            )
            return grupo.cantidad_disponible

        assert disponible() == Decimal(10)
        escritura.rollback()
        assert disponible() == Decimal(10)
        compromiso = crear_compromiso(escritura, datos, cantidad=Decimal(3))
        escritura.commit()
        assert disponible() == Decimal(7)
        compromiso.estado = EstadoCompromiso.LIBERADO
        compromiso.liberado_en = datetime.now(UTC)
        compromiso.liberado_por_id = datos.integracion.id
        escritura.commit()
        assert disponible() == Decimal(10)
        assert not lectura.new and not lectura.dirty and not lectura.deleted


def test_jwt_permisos_filtros_y_openapi(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    for cuenta in (datos.admin, datos.integracion, cuenta_ong(session, datos)):
        assert client.get(RUTA, headers=auth(cuenta)).status_code == 200
    for headers in ({}, {"Authorization": "Bearer invalido"}):
        assert client.get(RUTA, headers=headers).status_code == 401
    for filtro in ("ongId", "capacidadId"):
        assert (
            client.get(
                RUTA, headers=auth(datos.admin), params={filtro: str(uuid4())}
            ).json()["recursos"]
            == []
        )
        assert (
            client.get(
                RUTA, headers=auth(datos.admin), params={filtro: "invalido"}
            ).status_code
            == 422
        )
    datos.origen.activo = False
    session.commit()
    assert client.get(RUTA, headers=auth(datos.integracion)).status_code == 403
    assert client.get("/openapi.json").json()["paths"][RUTA]["get"]["security"] == [
        {"HTTPBearer": []}
    ]
