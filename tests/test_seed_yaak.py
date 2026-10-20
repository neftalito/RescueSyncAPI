"""Seed Yaak destructivo, transaccional y utilizable desde los endpoints reales."""

from collections.abc import Iterator
from copy import deepcopy
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from test_database_models import crear_compromiso, crear_datos, verificar_diferidas

from app.core.config import get_settings
from app.db.models import Capacidad, Compromiso, Cuenta, Ong, Proyecto, Recurso, Unidad
from app.db.session import get_db
from app.main import app
from app.scripts.seed_yaak import PASSWORD_YAAK
from app.services import mantenimiento

PASSWORD = "password-mantenimiento-test-seed-yaak-2026"
HEADERS = {"X-DB-Maintenance-Password": PASSWORD}
URL = "/api/v1/mantenimiento/seed-yaak"
BODY = {
    "confirmacion": "BORRAR_Y_PREPARAR_YAAK",
    "runId": "YAAK2026",
    "integracion": {
        "identificadorLogin": "integracion-rescuesync",
        "password": "demo-integracion-yaak-2026-123456",
        "sistemaOrigen": "rescuesync-local",
    },
}


@pytest.fixture
def yaak_client(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    def database() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(get_settings(), "db_maintenance_password", SecretStr(PASSWORD))
    return client


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-DB-Maintenance-Password": "incorrecta"}, {"Authorization": "Bearer jwt"}],
)
def test_sin_credencial_no_abre_db(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    monkeypatch.setattr(get_settings(), "db_maintenance_password", SecretStr(PASSWORD))
    database = Mock(side_effect=AssertionError("No abrir la base"))
    app.dependency_overrides[get_db] = database
    assert client.post(URL, headers=headers, json=BODY).status_code == 401
    database.assert_not_called()


def test_desactivado(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "db_maintenance_password", None)
    assert client.post(URL, headers=HEADERS, json=BODY).status_code == 403


@pytest.mark.parametrize("entorno", ["test", "production"])
def test_flush_y_seed_dejan_solo_escenario_y_logins_utilizables(
    yaak_client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    entorno: str,
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", entorno)
    anteriores = crear_datos(session)
    crear_compromiso(session, anteriores)
    verificar_diferidas(session)
    session.commit()
    anterior_id = anteriores.ong.id
    revision = session.scalar(text("SELECT version_num FROM alembic_version"))
    respuesta = yaak_client.post(URL, headers=HEADERS, json=BODY)
    assert respuesta.status_code == 200
    datos = respuesta.json()
    for model, count in [
        (Unidad, 31),
        (Capacidad, 57),
        (Ong, 5),
        (Cuenta, 8),
        (Recurso, 7),
        (Proyecto, 0),
        (Compromiso, 0),
    ]:
        assert session.scalar(select(func.count()).select_from(model)) == count
    assert session.get(Ong, anterior_id) is None
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == revision
    assert BODY["integracion"]["password"] not in respuesta.text
    assert PASSWORD_YAAK not in respuesta.text and PASSWORD not in respuesta.text
    assert session.get(
        Recurso, UUID(datos["referencias"]["aguaAId"])
    ).cantidad_total == Decimal("10.125")
    for key, login in datos["identificadoresLogin"].items():
        password = (
            BODY["integracion"]["password"] if key == "integracion" else PASSWORD_YAAK
        )
        autenticada = yaak_client.post(
            "/api/v1/login", json={"identificadorLogin": login, "password": password}
        )
        assert autenticada.status_code == (401 if key == "inactiva" else 200)
        if key == "inactiva":
            continue
        token = autenticada.json()["access_token"]
        me = yaak_client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == (403 if key in {"suspendida", "baja"} else 200)
        if key == "tecnica":
            assert autenticada.json()["expires_in"] == 300
            assert me.json()["proposito"] == "TECNICA_ONG"


def test_repetir_reinicia_stock_y_referencias_sin_acumular(
    yaak_client: TestClient, session: Session
) -> None:
    primera = yaak_client.post(URL, headers=HEADERS, json=BODY).json()
    recurso_id = UUID(primera["referencias"]["personalAId"])
    recurso = session.get(Recurso, recurso_id)
    assert recurso is not None
    recurso.cantidad_total = Decimal("1")
    session.commit()
    repetida = yaak_client.post(URL, headers=HEADERS, json=BODY)
    assert repetida.status_code == 200 and repetida.json() == primera
    session.expire_all()
    restaurado = session.get(Recurso, recurso_id)
    assert restaurado is not None and restaurado.cantidad_total == Decimal("14")
    assert session.scalar(select(func.count()).select_from(Cuenta)) == 8
    nueva = yaak_client.post(URL, headers=HEADERS, json={**BODY, "runId": "OTRA2026"})
    assert nueva.status_code == 200
    assert nueva.json()["referencias"] != primera["referencias"]
    assert session.scalar(select(func.count()).select_from(Ong)) == 5


@pytest.mark.parametrize("fallo", ["carga", "commit"])
def test_fallo_revierte_incluso_flush_sin_exponer_sql(
    yaak_client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    fallo: str,
) -> None:
    anterior = crear_datos(session)
    verificar_diferidas(session)
    session.commit()
    anterior_id = anterior.ong.id
    error = SQLAlchemyError(f"SQL privado {PASSWORD}")
    if fallo == "carga":
        monkeypatch.setattr(
            mantenimiento, "cargar_escenario_yaak", Mock(side_effect=error)
        )
    else:
        monkeypatch.setattr(session, "commit", Mock(side_effect=error))
    respuesta = yaak_client.post(URL, headers=HEADERS, json=BODY)
    assert respuesta.status_code == 503
    assert "SQL" not in respuesta.text and PASSWORD not in respuesta.text
    session.expire_all()
    assert session.get(Ong, anterior_id) is not None
    assert session.scalar(select(func.count()).select_from(Ong)) == 1


@pytest.mark.parametrize(
    "caso", ["sin-body", "confirmacion", "runId", "extra", "password", "colision"]
)
def test_body_invalido_no_vacia(
    yaak_client: TestClient, session: Session, caso: str
) -> None:
    anterior = crear_datos(session)
    verificar_diferidas(session)
    session.commit()
    anterior_id = anterior.ong.id
    datos = deepcopy(BODY)
    if caso == "confirmacion":
        datos["confirmacion"] = "SI"
    elif caso == "runId":
        datos["runId"] = "minuscula invalida"
    elif caso == "extra":
        datos["extra"] = True
    elif caso == "password":
        datos["integracion"]["password"] = "corta"
    elif caso == "colision":
        datos["integracion"]["identificadorLogin"] = "ADMIN.YAAK@example.org"
    respuesta = yaak_client.post(
        URL, headers=HEADERS, **({} if caso == "sin-body" else {"json": datos})
    )
    assert respuesta.status_code == 422
    assert session.get(Ong, anterior_id) is not None


def test_lock_compartido_impide_flush_antes_de_poder_cargar(
    client: TestClient, engine_migrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "db_maintenance_password", SecretStr(PASSWORD))
    monkeypatch.setattr(get_settings(), "operacion_lock_timeout_ms", 40)
    with Session(engine_migrado) as bloqueante, Session(engine_migrado) as db:
        bloqueante.execute(text("SELECT pg_advisory_xact_lock(73844, 0)"))

        def database() -> Iterator[Session]:
            yield db

        app.dependency_overrides[get_db] = database
        respuesta = client.post(URL, headers=HEADERS, json=BODY)
        assert respuesta.status_code == 503
        assert db.scalar(select(func.count()).select_from(Capacidad)) == 56
        bloqueante.rollback()
