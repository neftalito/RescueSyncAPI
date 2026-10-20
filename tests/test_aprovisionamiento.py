"""Alta técnica, reintentos y aislamiento de emisores sobre PostgreSQL real."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from test_inventario import inventory_client as inventory_client_fixture

from app.core.security import emitir_token, generar_password_hash
from app.db.models import (
    AprovisionamientoOng,
    Cuenta,
    EstadoOng,
    Ong,
    PropositoCuenta,
    RolNacional,
    SistemaOrigen,
)
from app.schemas.aprovisionamiento import AprovisionamientoRequest
from app.services.aprovisionamiento import aprovisionar_ong

inventory_client = inventory_client_fixture
DATOS = {
    "nombre": "Rescate automático",
    "password": "secreto-aleatorio-de-backend-con-32-caracteres",
}


def emisor(session: Session) -> Cuenta:
    origen = SistemaOrigen(codigo=uuid4().hex, nombre="Instalación local")
    session.add(origen)
    session.flush()
    cuenta = Cuenta(
        identificador_login=f"emisor-{uuid4().hex}",
        password_hash=generar_password_hash("clave-de-integracion-123"),
        rol=RolNacional.INTEGRACION,
        sistema_origen_id=origen.id,
    )
    session.add(cuenta)
    session.commit()
    return cuenta


def headers(cuenta: Cuenta) -> dict[str, str]:
    return {"Authorization": f"Bearer {emitir_token(cuenta.id)}"}


def test_alta_sin_contacto_genera_identificador_y_acceso_inmediato(
    inventory_client: TestClient,
    session: Session,
) -> None:
    cuenta = emisor(session)
    referencia = uuid4()
    ruta = f"/api/v1/integraciones/ongs/{referencia}"
    respuesta = inventory_client.put(ruta, headers=headers(cuenta), json=DATOS)
    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    datos = respuesta.json()
    assert "password" not in respuesta.text
    ong = session.get(Ong, datos["ong"]["id"])
    assert ong is not None and ong.estado == EstadoOng.HABILITADA
    assert ong.email_contacto is None
    assert (
        ong.identificador_institucional
        == f"rs:{cuenta.sistema_origen_id.hex}:{referencia.hex}"
    )
    assert (
        inventory_client.put(ruta, headers=headers(cuenta), json=DATOS).json() == datos
    )
    tecnica = session.get(Cuenta, datos["cuentaId"])
    assert tecnica is not None and tecnica.proposito == PropositoCuenta.TECNICA_ONG
    assert tecnica.version_credencial == 1
    assert tecnica.password_hash != DATOS["password"]
    login = inventory_client.post(
        "/api/v1/login",
        json={
            "identificadorLogin": datos["identificadorLogin"],
            "password": DATOS["password"],
        },
    )
    assert login.status_code == 200 and login.json()["expires_in"] == 300
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (
        inventory_client.get(
            f"/api/v1/ongs/{ong.id}/recursos", headers=auth
        ).status_code
        == 200
    )
    assert (
        inventory_client.get(
            f"/api/v1/ongs/{uuid4()}/recursos", headers=auth
        ).status_code
        == 403
    )
    assert (
        inventory_client.put(
            ruta, headers=headers(cuenta), json={**DATOS, "nombre": "Otro"}
        ).status_code
        == 409
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(AprovisionamientoOng)
            .where(
                AprovisionamientoOng.sistema_origen_id == cuenta.sistema_origen_id,
                AprovisionamientoOng.referencia_local == referencia,
            )
        )
        == 1
    )


@pytest.mark.parametrize("rol", [None, RolNacional.ONG, RolNacional.ADMIN_NACIONAL])
def test_alta_no_es_publica_ni_accesible_por_otro_rol(
    inventory_client: TestClient,
    session: Session,
    rol: RolNacional | None,
) -> None:
    auth: dict[str, str] = {}
    if rol is not None:
        ong = Ong(
            nombre="Otra", identificador_institucional="otra", email_contacto=None
        )
        session.add(ong)
        session.flush()
        cuenta = Cuenta(
            identificador_login="otro",
            password_hash=generar_password_hash("clave-segura-123"),
            rol=rol,
            ong_id=ong.id if rol == RolNacional.ONG else None,
        )
        session.add(cuenta)
        session.commit()
        auth = headers(cuenta)
    referencia = uuid4()
    respuesta = inventory_client.put(
        f"/api/v1/integraciones/ongs/{referencia}", headers=auth, json=DATOS
    )
    assert respuesta.status_code == (401 if rol is None else 403)
    assert (
        session.scalar(
            select(func.count())
            .select_from(AprovisionamientoOng)
            .where(
                AprovisionamientoOng.referencia_local == referencia,
            )
        )
        == 0
    )


def test_referencia_se_aisla_por_emisor_y_revocacion_no_se_recupera(
    inventory_client: TestClient,
    session: Session,
) -> None:
    uno, dos = emisor(session), emisor(session)
    ruta = f"/api/v1/integraciones/ongs/{uuid4()}"
    primera = inventory_client.put(ruta, headers=headers(uno), json=DATOS).json()
    segunda = inventory_client.put(
        ruta,
        headers=headers(dos),
        json={**DATOS, "emailContacto": "contacto@example.org"},
    ).json()
    assert primera["ong"]["id"] != segunda["ong"]["id"]
    tecnica = session.get(Cuenta, primera["cuentaId"])
    assert tecnica is not None
    tecnica.activa = False
    session.commit()
    assert (
        inventory_client.put(ruta, headers=headers(uno), json=DATOS).status_code == 403
    )
    session.refresh(tecnica)
    assert tecnica.activa is False
    origen = session.get(SistemaOrigen, dos.sistema_origen_id)
    assert origen is not None
    origen.activo = False
    session.commit()
    assert (
        inventory_client.put(ruta, headers=headers(dos), json=DATOS).status_code == 403
    )


def test_reintentos_concurrentes_crean_una_sola_ong(engine_migrado: Engine) -> None:
    with Session(engine_migrado) as db:
        cuenta = emisor(db)
        cuenta_id = cuenta.id
    referencia = uuid4()

    def ejecutar(_: int) -> UUID:
        with Session(engine_migrado) as db:
            return aprovisionar_ong(
                db, cuenta_id, referencia, AprovisionamientoRequest(**DATOS)
            ).ong.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(ejecutar, range(2)))
    assert resultados[0] == resultados[1]
    with Session(engine_migrado) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AprovisionamientoOng)
                .where(
                    AprovisionamientoOng.sistema_origen_id == cuenta.sistema_origen_id
                )
            )
            == 1
        )


def test_bootstrap_integracion_no_reemplaza_identidades(session: Session) -> None:
    from app.scripts.bootstrap_admin import CuentaAdminCreate
    from app.scripts.bootstrap_integracion import crear_integracion

    datos = CuentaAdminCreate(login="alta-local", password="clave-integracion-123")
    cuenta = crear_integracion(session, datos, "rescuesync-local")
    session.commit()
    assert cuenta.rol == RolNacional.INTEGRACION and cuenta.ong_id is None
    hash_original = cuenta.password_hash
    with pytest.raises(ValueError, match="ya existe"):
        crear_integracion(session, datos, "rescuesync-local")
    assert cuenta.password_hash == hash_original


def test_migracion_revierte_contacto_opcional_sin_eliminar_ong(
    engine_migrado: Engine,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    with Session(engine_migrado) as db:
        ong = Ong(nombre="Sin contacto", identificador_institucional=uuid4().hex)
        db.add(ong)
        db.flush()
        ong_id = ong.id
        db.commit()
    with engine_migrado.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "20261015_0003")
        assert (
            connection.scalar(
                text("SELECT email_contacto FROM ong WHERE id = :id"), {"id": ong_id}
            )
            == f"no-informado+{ong_id}@example.invalid"
        )
        command.upgrade(config, "head")
        assert (
            connection.scalar(
                text("SELECT count(*) FROM ong WHERE id = :id"), {"id": ong_id}
            )
            == 1
        )
