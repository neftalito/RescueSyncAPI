"""Perfiles descriptivos sin acreditar ni limitar a las instituciones."""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from soporte_nacional import auth, client, cuenta_ong, datos
from sqlalchemy.orm import Session
from test_database_models import DatosNacionales, crear_compromiso

from app.db.models import EstadoOng, Ong, Recurso
from app.services.perfiles import consultar_perfiles

__all__ = ["client", "datos"]


def test_perfil_agrupa_recursos_y_compromisos(
    session: Session, datos: DatosNacionales
) -> None:
    session.add(
        Recurso(
            ong_id=datos.ong.id,
            capacidad_id=datos.capacidad.id,
            codigo_interno="otro",
            nombre="Otro equipo",
            cantidad_total=Decimal(5),
        )
    )
    crear_compromiso(session, datos, cantidad=Decimal(3))
    crear_compromiso(session, datos, cantidad=Decimal(2))
    session.commit()
    p = consultar_perfiles(session, ong_ids={datos.ong.id})[datos.ong.id]
    assert len(p.capacidades_declaradas) == 1
    c = p.capacidades_declaradas[0]
    assert (c.cantidad_total, c.cantidad_comprometida, c.cantidad_disponible) == (
        15,
        5,
        10,
    )


def test_stock_agotado_conserva_capacidad(
    session: Session, datos: DatosNacionales
) -> None:
    crear_compromiso(session, datos, cantidad=Decimal(10))
    session.commit()
    p = consultar_perfiles(session, ong_ids={datos.ong.id})[datos.ong.id]
    assert p.capacidades_declaradas[0].cantidad_disponible == 0
    assert p.capacidades_declaradas[0].cantidad_total == 10


def test_directorio_incluye_alta_automatica_sin_inventario(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    nueva = Ong(nombre="Sin recursos", identificador_institucional=f"nueva:{uuid4()}")
    session.add(nueva)
    session.commit()
    assert nueva.estado == EstadoOng.HABILITADA
    assert nueva.habilitada_por_id is None and nueva.habilitada_en is None
    response = client.get("/api/v1/ongs", headers=auth(datos.admin))
    assert response.status_code == 200
    p = next(p for p in response.json()["ongs"] if p["ongId"] == str(nueva.id))
    assert p["capacidadesDeclaradas"] == []
    filtrado = client.get(
        "/api/v1/ongs",
        headers=auth(datos.admin),
        params={
            "capacidadId": str(datos.capacidad.id),
        },
    )
    assert all(p["ongId"] != str(nueva.id) for p in filtrado.json()["ongs"])


@pytest.mark.parametrize("estado", [EstadoOng.SUSPENDIDA, EstadoOng.BAJA])
def test_directorio_excluye_bajas_y_suspensiones(
    client: TestClient, session: Session, datos: DatosNacionales, estado: EstadoOng
) -> None:
    datos.ong.estado = estado
    session.commit()
    response = client.get("/api/v1/ongs", headers=auth(datos.admin))
    assert not any(p["ongId"] == str(datos.ong.id) for p in response.json()["ongs"])


def test_perfil_protege_identidad_y_retira_rutas(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    ruta = f"/api/v1/ongs/{datos.ong.id}/perfil-competencia"
    assert client.get(ruta).status_code == 401
    cuenta = cuenta_ong(session, datos)
    response = client.get(ruta, headers=auth(cuenta))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "acreditaciones" not in response.json()
    ajena = f"/api/v1/ongs/{uuid4()}/perfil-competencia"
    assert client.get(ajena, headers=auth(cuenta)).status_code == 403
    assert client.get(ajena, headers=auth(datos.admin)).status_code == 404
    assert client.get("/api/v1/certificaciones").status_code == 404
    assert client.get(f"/api/v1/ongs/{datos.ong.id}/certificaciones").status_code == 404


def test_alta_inventario_compromiso_y_liberacion_sin_certificados(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    from test_compromisos import peticion
    from test_validaciones import snapshot

    from app.db.models import Cuenta, NivelRiesgo
    from app.schemas.proyectos import FinalizacionRequest
    from app.services.compromisos import registrar_compromisos
    from app.services.liberaciones import liberar_compromiso
    from app.services.validaciones import validar_snapshot

    alta = client.post(
        "/api/v1/ongs",
        json={
            "nombre": "ONG recién registrada",
            "identificadorInstitucional": f"sin-cert:{uuid4()}",
            "emailContacto": "contacto@example.org",
            "identificadorLogin": f"nueva-{uuid4()}@example.test",
            "password": "Credencial-de-prueba-2026",
        },
    )
    assert alta.status_code == 201, alta.text
    ong = session.get(Ong, alta.json()["id"])
    assert ong is not None and ong.estado == EstadoOng.HABILITADA
    assert ong.habilitada_por_id is None
    from sqlalchemy import select

    cuenta = session.scalar(select(Cuenta).where(Cuenta.ong_id == ong.id))
    assert cuenta is not None
    response = client.post(
        f"/api/v1/ongs/{ong.id}/recursos",
        headers=auth(cuenta),
        json={
            "capacidadId": str(datos.capacidad.id),
            "codigoInterno": "propio",
            "nombre": "Equipo nuevo",
            "cantidadTotal": "10.000",
        },
    )
    assert response.status_code == 201, response.text
    recurso = session.get(Recurso, response.json()["id"])
    assert recurso is not None
    datos.ong, datos.recurso = ong, recurso
    solicitud = snapshot(datos)
    solicitud.gravedad = NivelRiesgo.CRITICA
    solicitud.lotes[0].riesgo_requerido = NivelRiesgo.CRITICA
    assert validar_snapshot(session, solicitud).aportes[0].motivos == []
    pedido = peticion(datos)
    pedido.aportes[0].riesgo_requerido = NivelRiesgo.CRITICA
    compromiso = registrar_compromisos(
        session, datos.integracion, pedido, "sin-certificados"
    )
    perfil = consultar_perfiles(session, ong_ids={ong.id})[ong.id]
    assert perfil.capacidades_declaradas[0].cantidad_disponible == 4
    liberar_compromiso(
        session,
        datos.integracion,
        compromiso.compromiso_ids[0],
        FinalizacionRequest(case_id="100"),
        "liberar-sin-certificados",
    )
    perfil = consultar_perfiles(session, ong_ids={ong.id})[ong.id]
    assert perfil.capacidades_declaradas[0].cantidad_disponible == 10
