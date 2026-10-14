"""Reservas multiONG, idempotencia, permisos, rollback y disponibilidad observable."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_certificaciones import auth, client, cuenta_ong, datos
from test_database_models import DatosNacionales, crear_datos

from app.db.models import (
    Compromiso,
    CompromisoItem,
    EstadoOng,
    EstadoProyecto,
    NivelRiesgo,
    OperacionIdempotente,
    Proyecto,
    Recurso,
)
from app.schemas.certificaciones import AcreditacionCreate
from app.schemas.compromisos import AporteCompromiso, CompromisoRequest
from app.services.certificaciones import otorgar_acreditacion
from app.services.compromisos import registrar_compromisos
from app.services.inventario import cantidad_comprometida
from app.services.operaciones import ErrorOperacion

__all__ = ["client", "datos"]
RUTA = "/api/v1/compromisos"


def peticion(datos: DatosNacionales, cantidad: str = "6") -> CompromisoRequest:
    return CompromisoRequest(
        sistema_origen=datos.origen.codigo,
        id_emergencia="101",
        case_id="100",
        convocatoria_id="20",
        adjudicacion_id="seleccion-101-1",
        aportes=[
            AporteCompromiso(
                oferta_id="30",
                version=1,
                lote_id="40",
                aporte_id="50",
                ong_nacional_id=datos.ong.id,
                recurso_nacional_id=datos.recurso.id,
                capacidad_nacional_id=datos.capacidad.id,
                riesgo_requerido=NivelRiesgo.MEDIA,
                cantidad=Decimal(cantidad),
                unidad=datos.capacidad.unidad,
            )
        ],
    )


def headers(datos: DatosNacionales, clave: str = "adjudicacion-1") -> dict[str, str]:
    return {**auth(datos.integracion), "Idempotency-Key": clave}


def test_post_get_y_confirmacion_minima(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    p = peticion(datos)
    response = client.post(
        RUTA, headers=headers(datos), json=p.model_dump(mode="json", by_alias=True)
    )
    assert response.status_code == 201, response.text
    confirmacion = response.json()
    assert len(confirmacion["compromisoIds"]) == 1
    cid = confirmacion["compromisoIds"][0]
    consulta = client.get(f"{RUTA}/{cid}", headers=auth(datos.integracion))
    assert consulta.status_code == 200
    body = consulta.json()
    assert body["idEmergencia"] == "101" and body["caseId"] == "100"
    assert body["ongNacionalId"] == str(datos.ong.id) and body["estado"] == "ACTIVO"
    assert body["items"][0]["cantidad"] == "6.000"
    assert body["items"][0]["convocatoriaId"] == "20"
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(6)
    operacion = session.get(OperacionIdempotente, UUID(confirmacion["operacionId"]))
    assert operacion is not None and operacion.respuesta_minima == confirmacion
    assert set(confirmacion) == {
        "operacionId",
        "proyectoId",
        "compromisoIds",
        "registradoEn",
    }
    assert (
        response.headers["cache-control"]
        == consulta.headers["cache-control"]
        == "no-store"
    )
    inventario = client.get(
        f"/api/v1/ongs/{datos.ong.id}/recursos", headers=auth(datos.admin)
    )
    assert inventario.json()[0]["cantidadDisponible"] == "4.000"


def test_reintentos_equivalentes_y_conflictos(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    p = peticion(datos, "2")
    segundo = p.aportes[0].model_copy(
        update={"aporte_id": "51", "cantidad": Decimal(4)}
    )
    p.aportes.append(segundo)
    response = client.post(
        RUTA, headers=headers(datos), json=p.model_dump(mode="json", by_alias=True)
    )
    assert response.status_code == 201
    p.aportes.reverse()
    body = p.model_dump(mode="json", by_alias=True)
    body["aportes"][0]["cantidad"] = "4.0"
    repetida = client.post(RUTA, headers=headers(datos), json=body)
    assert repetida.status_code == 201 and repetida.json() == response.json()
    assert (
        client.post(RUTA, headers=headers(datos, "otra-clave"), json=body).status_code
        == 409
    )
    body["aportes"][0]["cantidad"] = "3.000"
    assert client.post(RUTA, headers=headers(datos), json=body).status_code == 409
    assert session.scalar(select(func.count()).select_from(Compromiso)) == 1
    assert session.scalar(select(func.count()).select_from(CompromisoItem)) == 2
    assert session.scalar(select(func.count()).select_from(OperacionIdempotente)) == 1


def test_reutiliza_proyecto_y_rechaza_otro_caso(
    client: TestClient, datos: DatosNacionales
) -> None:
    p = peticion(datos, "2")
    first = client.post(
        RUTA, headers=headers(datos), json=p.model_dump(mode="json", by_alias=True)
    )
    p.adjudicacion_id = "seleccion-2"
    second = client.post(
        RUTA,
        headers=headers(datos, "segunda"),
        json=p.model_dump(mode="json", by_alias=True),
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["proyectoId"] == second.json()["proyectoId"]
    p.case_id = "999"
    p.adjudicacion_id = "seleccion-3"
    assert (
        client.post(
            RUTA,
            headers=headers(datos, "tercera"),
            json=p.model_dump(mode="json", by_alias=True),
        ).status_code
        == 409
    )


def agregar_participante(
    session: Session, datos: DatosNacionales, p: CompromisoRequest
) -> Recurso:
    otra = crear_datos(session, f"multi-{uuid4().hex}")
    otorgar_acreditacion(
        session,
        otra.admin.id,
        AcreditacionCreate(
            ong_id=otra.ong.id,
            certificacion_id=datos.certificacion.id,
            emisor="Autoridad",
            numero_credencial="rescate-propio",
            vigente_desde=datos.acreditacion.vigente_desde,
            vigente_hasta=datos.acreditacion.vigente_hasta,
        ),
    )
    r = Recurso(
        ong_id=otra.ong.id,
        capacidad_id=datos.capacidad.id,
        codigo_interno="multi",
        nombre="Personal",
        cantidad_total=Decimal(10),
    )
    session.add(r)
    session.flush()
    p.aportes.append(
        p.aportes[0].model_copy(
            update={
                "aporte_id": "51",
                "ong_nacional_id": otra.ong.id,
                "recurso_nacional_id": r.id,
            }
        )
    )
    session.commit()
    return r


@pytest.mark.parametrize("fallar", [False, True])
def test_multi_ong_es_atomico(
    session: Session, datos: DatosNacionales, fallar: bool
) -> None:
    p = peticion(datos)
    r = agregar_participante(session, datos, p)
    proyectos = session.scalar(select(func.count()).select_from(Proyecto))
    if fallar:
        p.aportes[1].cantidad = Decimal(11)
        with pytest.raises(ErrorOperacion):
            registrar_compromisos(session, datos.integracion, p, "multi")
        assert session.scalar(select(func.count()).select_from(Proyecto)) == proyectos
        assert (
            session.scalar(select(func.count()).select_from(OperacionIdempotente)) == 0
        )
        assert session.scalar(select(func.count()).select_from(Compromiso)) == 0
        assert cantidad_comprometida(session, r.id) == Decimal(0)
    else:
        resultado = registrar_compromisos(session, datos.integracion, p, "multi")
        assert len(resultado.compromiso_ids) == 2
        assert cantidad_comprometida(session, r.id) == Decimal(6)
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(
        0 if fallar else 6
    )


@pytest.mark.parametrize(
    "tipo",
    [
        "stock",
        "suma",
        "riesgo",
        "unidad",
        "fraccion",
        "inactivo",
        "suspendida",
        "desconocido",
        "capacidad",
    ],
)
def test_revalida_y_revierte_la_operacion(
    client: TestClient, session: Session, datos: DatosNacionales, tipo: str
) -> None:
    p = peticion(datos)
    a = p.aportes[0]
    if tipo == "stock":
        a.cantidad = Decimal(11)
    elif tipo == "suma":
        p.aportes.append(a.model_copy(update={"aporte_id": "51"}))
    elif tipo == "riesgo":
        a.riesgo_requerido = NivelRiesgo.CRITICA
    elif tipo == "unidad":
        a.unidad = "kg"
    elif tipo == "fraccion":
        a.cantidad = Decimal("1.125")
    elif tipo == "inactivo":
        datos.recurso.activo = False
    elif tipo == "suspendida":
        datos.ong.estado = EstadoOng.SUSPENDIDA
    elif tipo == "capacidad":
        a.capacidad_nacional_id = uuid4()
    else:
        a.recurso_nacional_id = uuid4()
    session.commit()
    before = session.scalar(select(func.count()).select_from(Proyecto))
    response = client.post(
        RUTA, headers=headers(datos), json=p.model_dump(mode="json", by_alias=True)
    )
    assert response.status_code == (
        404 if tipo in {"desconocido", "capacidad"} else 409
    ), response.text
    assert session.scalar(select(func.count()).select_from(Proyecto)) == before
    assert session.scalar(select(func.count()).select_from(Compromiso)) == 0
    assert session.scalar(select(func.count()).select_from(OperacionIdempotente)) == 0


def test_permisos_y_clave_requerida(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    p = peticion(datos)
    body = p.model_dump(mode="json", by_alias=True)
    assert (
        client.post(RUTA, headers=auth(datos.integracion), json=body).status_code == 422
    )
    assert (
        client.post(
            RUTA,
            headers={**auth(datos.integracion), "Idempotency-Key": "   "},
            json=body,
        ).status_code
        == 422
    )
    assert (
        client.post(RUTA, headers={"Idempotency-Key": "uno"}, json=body).status_code
        == 401
    )
    assert (
        client.post(
            RUTA,
            headers={**auth(cuenta_ong(session, datos)), "Idempotency-Key": "uno"},
            json=body,
        ).status_code
        == 403
    )
    otra = crear_datos(session, f"otro-{uuid4().hex}")
    session.commit()
    response = client.post(RUTA, headers=headers(datos), json=body)
    assert response.status_code == 201
    cid = response.json()["compromisoIds"][0]
    assert (
        client.get(f"{RUTA}/{cid}", headers=auth(otra.integracion)).status_code == 403
    )
    assert (
        client.get(f"{RUTA}/{uuid4()}", headers=auth(datos.integracion)).status_code
        == 404
    )
    datos.integracion.activa = False
    session.commit()
    assert client.post(RUTA, headers=headers(datos), json=body).status_code == 401


def test_proyecto_terminado_no_reserva(
    session: Session, datos: DatosNacionales
) -> None:
    p = peticion(datos)
    resultado = registrar_compromisos(session, datos.integracion, p, "primero")
    proyecto = session.get(Proyecto, resultado.proyecto_id)
    assert proyecto is not None
    # Este test aísla T32; T33 protegerá el cierre contra compromisos activos.
    from datetime import UTC, datetime

    admin_id = datos.admin.id
    proyecto.estado = EstadoProyecto.TERMINADO
    proyecto.cerrado_en = datetime.now(UTC)
    proyecto.cerrado_por_id = admin_id
    session.commit()
    p.adjudicacion_id = "otra"
    with pytest.raises(ErrorOperacion, match="terminado"):
        registrar_compromisos(session, datos.integracion, p, "segundo")
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(6)
