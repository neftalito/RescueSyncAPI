"""Aislamiento, expiración y revocación de accesos institucionales."""

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.core.security import emitir_token, generar_password_hash
from app.db.models import Cuenta, EstadoOng, Ong, PropositoCuenta, RolNacional
from app.db.session import get_db
from app.main import app
from app.schemas.cuentas_tecnicas import CredencialTecnica
from app.scripts import cuentas_tecnicas as cli
from app.services.cuentas_tecnicas import administrar_cuenta_tecnica


@pytest.fixture
def inventory_client(session: Session) -> Iterator[TestClient]:
    def database() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def identidades(session: Session) -> tuple[Cuenta, Ong]:
    admin = Cuenta(
        identificador_login="admin-tecnico@example.org",
        password_hash=generar_password_hash("clave-admin-123"),
        rol=RolNacional.ADMIN_NACIONAL,
    )
    ong = Ong(
        nombre="ONG técnica",
        identificador_institucional="registro:tecnica",
        email_contacto="ong@example.org",
    )
    session.add_all([admin, ong])
    session.commit()
    return admin, ong


def login(client: TestClient, datos: CredencialTecnica) -> dict[str, str]:
    response = client.post(
        "/api/v1/login",
        json={
            "identificadorLogin": datos.identificador_login,
            "password": datos.password.get_secret_value(),
        },
    )
    assert response.status_code == 200
    assert response.json()["expires_in"] == 300
    token = response.json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 300
    return {"Authorization": f"Bearer {token}"}


def test_rotar_revocar_y_aislar_ong(
    inventory_client: TestClient, session: Session
) -> None:
    admin, ong = identidades(session)
    datos = administrar_cuenta_tecnica(session, admin.id, ong.id, "crear")
    assert datos is not None and datos.password.get_secret_value() not in repr(datos)
    session.commit()
    headers = login(inventory_client, datos)
    perfil = inventory_client.get("/api/v1/me", headers=headers)
    assert perfil.json()["proposito"] == "TECNICA_ONG"
    assert perfil.json()["ongId"] == str(ong.id)
    assert (
        inventory_client.get(
            f"/api/v1/ongs/{uuid4()}/recursos", headers=headers
        ).status_code
        == 403
    )
    assert (
        inventory_client.get(
            f"/api/v1/ongs/{ong.id}/recursos", headers=headers
        ).status_code
        == 200
    )
    assert (
        inventory_client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {emitir_token(datos.cuenta_id)}"},
        ).status_code
        == 401
    )
    nueva = administrar_cuenta_tecnica(session, admin.id, ong.id, "rotar")
    assert nueva is not None and nueva.password != datos.password
    session.commit()
    assert inventory_client.get("/api/v1/me", headers=headers).status_code == 401
    headers = login(inventory_client, nueva)
    administrar_cuenta_tecnica(session, admin.id, ong.id, "revocar")
    session.commit()
    assert inventory_client.get("/api/v1/me", headers=headers).status_code == 401
    assert ong.estado == EstadoOng.HABILITADA


def test_solo_admin_crea_sin_reemplazar_cuentas_personales(session: Session) -> None:
    admin, ong = identidades(session)
    personal = Cuenta(
        identificador_login="personal@example.org",
        password_hash=generar_password_hash("clave-personal-123"),
        rol=RolNacional.ONG,
        ong_id=ong.id,
    )
    session.add(personal)
    session.commit()
    hash_original = personal.password_hash
    with pytest.raises(ValueError, match="administrativa"):
        administrar_cuenta_tecnica(session, personal.id, ong.id, "crear")
    administrar_cuenta_tecnica(session, admin.id, ong.id, "crear")
    with pytest.raises(ValueError, match="ya tiene"):
        administrar_cuenta_tecnica(session, admin.id, ong.id, "crear")
    assert personal.password_hash == hash_original
    assert personal.proposito == PropositoCuenta.PERSONAL


def test_cli_exporta_archivo_privado_sin_sobrescribir(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, ong = identidades(session)
    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli, "getpass", lambda _: "clave-admin-123")
    archivo = tmp_path / "credencial.json"
    args = [
        "--login",
        admin.identificador_login,
        "crear",
        "--ong",
        str(ong.id),
        "--salida",
        str(archivo),
    ]
    assert cli.main(args) == 0
    datos = json.loads(archivo.read_text())
    assert archivo.stat().st_mode & 0o777 == 0o600
    assert datos["password"] not in capsys.readouterr().out
    anterior = archivo.read_bytes()
    args[2] = "rotar"
    assert cli.main(args) == 1
    assert archivo.read_bytes() == anterior
    # La rotación fallida revierte junto con su transacción.
    cuenta = session.scalar(select(Cuenta).where(Cuenta.id == datos["cuentaId"]))
    assert cuenta is not None and cuenta.version_credencial == 1


def test_downgrade_desactiva_tecnicas_y_upgrade_conserva_personales(
    engine_migrado: Engine,
) -> None:
    """Ejecuta ambas direcciones sobre el schema descartable del módulo."""
    with Session(engine_migrado) as db:
        admin = Cuenta(
            identificador_login="admin-migracion@example.org",
            password_hash=generar_password_hash("clave-migracion-123"),
            rol=RolNacional.ADMIN_NACIONAL,
        )
        ong = Ong(
            nombre="ONG migración",
            identificador_institucional="registro:migracion",
            email_contacto="migracion@example.org",
        )
        db.add_all([admin, ong])
        db.flush()
        datos = administrar_cuenta_tecnica(db, admin.id, ong.id, "crear")
        assert datos is not None
        cuenta_id, admin_id = datos.cuenta_id, admin.id
        db.commit()
    with engine_migrado.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "20261014_0002")
        assert (
            connection.scalar(
                text("SELECT activa FROM cuenta WHERE id = :id"), {"id": cuenta_id}
            )
            is False
        )
        assert (
            connection.scalar(
                text("SELECT activa FROM cuenta WHERE id = :id"), {"id": admin_id}
            )
            is True
        )
        command.upgrade(config, "head")
