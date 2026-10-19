"""Cierre sin activos, conservación de auditoría y estado terminal de proyecto."""

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_certificaciones import auth, client, datos
from test_compromisos import headers, peticion
from test_database_models import DatosNacionales, crear_datos

from app.db.models import EstadoProyecto, Proyecto
from app.schemas.proyectos import FinalizacionRequest
from app.services.compromisos import registrar_compromisos
from app.services.inventario import cantidad_comprometida
from app.services.liberaciones import liberar_compromiso

__all__ = ["client", "datos"]


def test_cierre_no_libera_actividades_pendientes(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    r = registrar_compromisos(session, datos.integracion, peticion(datos), "crear")
    response = client.post(
        f"/api/v1/proyectos/{r.proyecto_id}/cierre",
        headers=headers(datos, "cerrar"),
        json={"caseId": "100"},
    )
    assert response.status_code == 409
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(6)
    assert session.get(Proyecto, r.proyecto_id).estado == EstadoProyecto.ABIERTO


def test_cierre_repetido_y_terminal_conserva_confirmaciones(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    p = peticion(datos)
    original = registrar_compromisos(session, datos.integracion, p, "crear")
    liberar_compromiso(
        session,
        datos.integracion,
        original.compromiso_ids[0],
        FinalizacionRequest(case_id="100"),
        "liberar",
    )
    url = f"/api/v1/proyectos/{original.proyecto_id}/cierre"
    primera = client.post(url, headers=headers(datos, "cerrar"), json={"caseId": "100"})
    repetida = client.post(
        url, headers=headers(datos, "cerrar"), json={"caseId": "100"}
    )
    assert primera.status_code == repetida.status_code == 200
    assert primera.json() == repetida.json()
    otra = client.post(
        url,
        headers={**auth(datos.admin), "Idempotency-Key": "otro-cierre"},
        json={"caseId": "100"},
    )
    assert (
        otra.status_code == 200
        and otra.json()["cerradoEn"] == primera.json()["cerradoEn"]
    )
    proyecto = session.get(Proyecto, original.proyecto_id)
    assert proyecto.estado == EstadoProyecto.TERMINADO
    assert proyecto.cerrado_por_id == datos.integracion.id
    replay = client.post(
        "/api/v1/compromisos",
        headers=headers(datos, "crear"),
        json=p.model_dump(mode="json", by_alias=True),
    )
    assert replay.status_code == 201 and replay.json() == original.model_dump(
        mode="json", by_alias=True
    )
    p.adjudicacion_id = "nueva"
    assert (
        client.post(
            "/api/v1/compromisos",
            headers=headers(datos, "nueva"),
            json=p.model_dump(mode="json", by_alias=True),
        ).status_code
        == 409
    )
    assert cantidad_comprometida(session, datos.recurso.id) == Decimal(0)
    assert primera.headers["cache-control"] == "no-store"


def test_cierre_ajeno_o_caso_invalido_no_termina(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    r = registrar_compromisos(session, datos.integracion, peticion(datos), "crear")
    liberar_compromiso(
        session,
        datos.integracion,
        r.compromiso_ids[0],
        FinalizacionRequest(case_id="100"),
        "lib",
    )
    url = f"/api/v1/proyectos/{r.proyecto_id}/cierre"
    assert (
        client.post(
            url, headers=headers(datos, "cerrar"), json={"caseId": "   "}
        ).status_code
        == 422
    )
    otra = crear_datos(session, f"otro-cierre-{uuid4().hex}")
    session.commit()
    assert (
        client.post(
            url, headers=headers(otra, "cerrar"), json={"caseId": "100"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            url, headers=headers(datos, "cerrar"), json={"caseId": "999"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/proyectos/{uuid4()}/cierre",
            headers=headers(datos, "cerrar"),
            json={"caseId": "100"},
        ).status_code
        == 404
    )
    assert session.get(Proyecto, r.proyecto_id).estado == EstadoProyecto.ABIERTO
