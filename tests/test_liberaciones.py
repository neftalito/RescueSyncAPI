"""Finalización por participante, historial inmutable y devolución exacta de stock."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_certificaciones import auth, client, cuenta_ong, datos
from test_compromisos import agregar_participante, headers, peticion
from test_database_models import DatosNacionales, crear_datos

from app.db.models import Compromiso, EstadoOng, Recurso
from app.schemas.certificaciones import AcreditacionCreate, RevocacionRequest
from app.schemas.proyectos import FinalizacionRequest
from app.services.certificaciones import otorgar_acreditacion, revocar_acreditacion
from app.services.compromisos import registrar_compromisos
from app.services.inventario import cantidad_comprometida
from app.services.liberaciones import liberar_compromiso

__all__ = ["client", "datos"]


def test_consorcio_libera_solo_la_ong_finalizada(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    p = peticion(datos)
    recurso_otra = agregar_participante(session, datos, p)
    resultado = registrar_compromisos(session, datos.integracion, p, "crear")
    propios = {
        session.get(Compromiso, cid).ong_id: cid for cid in resultado.compromiso_ids
    }
    cid = propios[datos.ong.id]
    response = client.post(
        f"/api/v1/compromisos/{cid}/liberacion",
        headers=headers(datos, "liberar-1"),
        json={"caseId": "100"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["ongNacionalId"] == str(datos.ong.id)
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(0)
    assert cantidad_comprometida(session, recurso_otra.id) == Decimal(6)
    inventario = client.get(
        f"/api/v1/ongs/{datos.ong.id}/recursos", headers=auth(datos.admin)
    )
    assert inventario.json()[0]["cantidadDisponible"] == "10.000"
    global_ = client.get(
        "/api/v1/recursos/disponibilidad",
        headers=auth(datos.admin),
        params={"capacidadId": str(datos.capacidad.id)},
    ).json()
    assert global_["recursos"][0]["cantidadDisponible"] == "14.000"
    assert (
        client.post(
            f"/api/v1/proyectos/{resultado.proyecto_id}/cierre",
            headers=headers(datos, "cierre"),
            json={"caseId": "100"},
        ).status_code
        == 409
    )
    otro_cid = next(cid for ong, cid in propios.items() if ong != datos.ong.id)
    liberar_compromiso(
        session,
        datos.integracion,
        otro_cid,
        FinalizacionRequest(case_id="100"),
        "liberar-2",
    )
    assert (
        client.post(
            f"/api/v1/proyectos/{resultado.proyecto_id}/cierre",
            headers=headers(datos, "cierre"),
            json={"caseId": "100"},
        ).status_code
        == 200
    )


def test_repeticiones_preservan_autor_fecha_items_y_total(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    r = registrar_compromisos(session, datos.integracion, peticion(datos), "crear")
    cid = r.compromiso_ids[0]
    url = f"/api/v1/compromisos/{cid}/liberacion"
    primera = client.post(
        url, headers=headers(datos, "liberar"), json={"caseId": "100"}
    )
    repetida = client.post(
        url, headers=headers(datos, "liberar"), json={"caseId": "100"}
    )
    assert primera.status_code == repetida.status_code == 200
    assert primera.json() == repetida.json()
    anterior = client.get(
        f"/api/v1/compromisos/{cid}", headers=auth(datos.admin)
    ).json()
    otra = client.post(
        url,
        headers={**auth(datos.admin), "Idempotency-Key": "segunda"},
        json={"caseId": "100"},
    )
    assert (
        otra.status_code == 200
        and otra.json()["liberadoEn"] == primera.json()["liberadoEn"]
    )
    actual = client.get(f"/api/v1/compromisos/{cid}", headers=auth(datos.admin)).json()
    assert actual == anterior and actual["estado"] == "LIBERADO"
    assert actual["liberadoPorId"] == str(datos.integracion.id)
    assert actual["items"][0]["cantidad"] == "6.000"
    assert session.get(Recurso, datos.recurso.id).cantidad_total == Decimal(10)
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(0)
    assert primera.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "situacion", ["suspendida", "baja", "recurso", "capacidad", "revocada", "vencida"]
)
def test_perdida_de_habilitacion_no_impide_liberar(
    session: Session, datos: DatosNacionales, situacion: str
) -> None:
    r = registrar_compromisos(session, datos.integracion, peticion(datos), "crear")
    if situacion == "suspendida":
        datos.ong.estado = EstadoOng.SUSPENDIDA
    elif situacion == "baja":
        datos.ong.estado = EstadoOng.BAJA
    elif situacion == "recurso":
        datos.recurso.activo = False
    elif situacion == "capacidad":
        datos.capacidad.activa = False
    else:
        revocar_acreditacion(
            session,
            datos.admin.id,
            RevocacionRequest(
                ong_id=datos.ong.id, acreditacion_id=datos.acreditacion.id, motivo="Fin"
            ),
        )
        if situacion == "vencida":
            otorgar_acreditacion(
                session,
                datos.admin.id,
                AcreditacionCreate(
                    ong_id=datos.ong.id,
                    certificacion_id=datos.certificacion.id,
                    emisor="Autoridad",
                    numero_credencial="historia-vencida",
                    vigente_desde=datetime.now(UTC) - timedelta(days=2),
                    vigente_hasta=datetime.now(UTC) - timedelta(days=1),
                ),
            )
    session.commit()
    liberar_compromiso(
        session,
        datos.integracion,
        r.compromiso_ids[0],
        FinalizacionRequest(case_id="100"),
        "liberar",
    )
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(0)


def test_destino_y_caso_forman_parte_de_la_clave(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    p = peticion(datos)
    primero = registrar_compromisos(session, datos.integracion, p, "crear")
    url = f"/api/v1/compromisos/{primero.compromiso_ids[0]}/liberacion"
    assert (
        client.post(
            url, headers=headers(datos, "liberar"), json={"caseId": "100"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            url, headers=headers(datos, "liberar"), json={"caseId": "999"}
        ).status_code
        == 409
    )
    p.adjudicacion_id = "otra"
    segundo = registrar_compromisos(session, datos.integracion, p, "crear-otra")
    url2 = f"/api/v1/compromisos/{segundo.compromiso_ids[0]}/liberacion"
    assert (
        client.post(
            url2, headers=headers(datos, "liberar"), json={"caseId": "100"}
        ).status_code
        == 409
    )
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(6)


def test_autorizacion_referencias_y_correlacion(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    r = registrar_compromisos(session, datos.integracion, peticion(datos), "crear")
    url = f"/api/v1/compromisos/{r.compromiso_ids[0]}/liberacion"
    body = {"caseId": "100"}
    assert (
        client.post(
            url, headers=headers(datos, "lib"), json={"caseId": "   "}
        ).status_code
        == 422
    )
    assert (
        client.post(url, headers=auth(datos.integracion), json=body).status_code == 422
    )
    assert (
        client.post(url, headers={"Idempotency-Key": "lib"}, json=body).status_code
        == 401
    )
    assert (
        client.post(
            url,
            headers={**auth(cuenta_ong(session, datos)), "Idempotency-Key": "lib"},
            json=body,
        ).status_code
        == 403
    )
    otra = crear_datos(session, f"otro-lib-{uuid4().hex}")
    session.commit()
    assert client.post(url, headers=headers(otra, "lib"), json=body).status_code == 403
    assert (
        client.post(
            url, headers=headers(datos, "lib"), json={"caseId": "999"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/compromisos/{uuid4()}/liberacion",
            headers=headers(datos, "lib"),
            json=body,
        ).status_code
        == 404
    )
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(6)
