"""Autorización, recuperación tras flush y atomicidad sobre PostgreSQL real."""

from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from test_database_models import crear_compromiso, crear_datos, verificar_diferidas

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import Capacidad, Cuenta, Ong, Recurso, Unidad
from app.db.session import get_db
from app.main import app
from app.scripts.seed_admin import ADMIN_DEMO_ID

PASSWORD = "password-privada-mantenimiento-prueba-2026"
HEADERS = {"X-DB-Maintenance-Password": PASSWORD}
RUTAS = ("seed", "seed-masivo", "flush")
MASIVO = {"seed": 2026, "ongs": 2, "recursosPorOng": 4, "batchSize": 2}


@pytest.fixture
def mantenimiento_client(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    """Reemplaza sólo la sesión; conserva la autenticación real del endpoint."""

    def database() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(get_settings(), "db_maintenance_password", SecretStr(PASSWORD))
    return client


@pytest.mark.parametrize("ruta", RUTAS)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-DB-Maintenance-Password": "incorrecta"},
        {"Authorization": "Bearer un-jwt-no-autoriza"},
    ],
)
def test_credencial_incorrecta_no_consulta_ni_modifica_db(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    ruta: str,
    headers: dict[str, str],
) -> None:
    monkeypatch.setattr(get_settings(), "db_maintenance_password", SecretStr(PASSWORD))
    database = Mock(side_effect=AssertionError("No debe abrirse la base"))
    app.dependency_overrides[get_db] = database
    respuesta = client.post(
        f"/api/v1/mantenimiento/{ruta}", headers=headers, json=MASIVO
    )
    assert respuesta.status_code == 401
    assert respuesta.json() == {
        "detail": "La contraseña de mantenimiento no es válida."
    }
    database.assert_not_called()


@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_configuracion_desactiva_mantenimiento(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    ruta: str,
) -> None:
    monkeypatch.setattr(get_settings(), "db_maintenance_password", None)
    respuesta = client.post(f"/api/v1/mantenimiento/{ruta}", headers=HEADERS)
    assert respuesta.status_code == 403
    assert PASSWORD not in respuesta.text


@pytest.mark.parametrize("entorno", ["test", "production"])
def test_seed_normal_crea_login_admin_y_repetir_conserva_stock_y_password(
    mantenimiento_client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    entorno: str,
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", entorno)
    respuesta = mantenimiento_client.post("/api/v1/mantenimiento/seed", headers=HEADERS)
    assert respuesta.status_code == 200
    assert session.scalar(select(func.count()).select_from(Ong)) == 2
    assert session.scalar(select(func.count()).select_from(Cuenta)) == 5
    assert session.scalar(select(func.count()).select_from(Recurso)) == 4
    admin = session.get(Cuenta, ADMIN_DEMO_ID)
    assert admin is not None
    hash_original = admin.password_hash
    recurso = session.scalar(select(Recurso))
    assert recurso is not None
    recurso.cantidad_total = Decimal(73)
    session.commit()
    assert (
        mantenimiento_client.post(
            "/api/v1/mantenimiento/seed", headers=HEADERS
        ).status_code
        == 200
    )
    session.refresh(recurso)
    session.refresh(admin)
    assert recurso.cantidad_total == 73 and admin.password_hash == hash_original
    assert session.scalar(select(func.count()).select_from(Cuenta)) == 5
    login = mantenimiento_client.post(
        "/api/v1/login",
        json={
            "identificadorLogin": "admin.nacional.demo@rescuesync.org",
            "password": "admin-nacional-demo123",
        },
    )
    assert login.status_code == 200


@pytest.mark.parametrize("entorno", ["test", "production"])
def test_seed_masivo_informa_solo_filas_agregadas(
    mantenimiento_client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    entorno: str,
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", entorno)
    respuesta = mantenimiento_client.post(
        "/api/v1/mantenimiento/seed-masivo",
        headers=HEADERS,
        json=MASIVO,
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "operacion": "seed-masivo",
        "mensaje": "Seed masivo confirmado.",
        "ongs": 2,
        "cuentas": 5,
        "recursos": 8,
    }
    repetida = mantenimiento_client.post(
        "/api/v1/mantenimiento/seed-masivo",
        headers=HEADERS,
        json=MASIVO,
    )
    assert repetida.status_code == 200
    assert [repetida.json()[campo] for campo in ("ongs", "cuentas", "recursos")] == [
        0,
        0,
        0,
    ]
    assert session.scalar(select(func.count()).select_from(Recurso)) == 8


@pytest.mark.parametrize("ruta", ["seed", "seed-masivo"])
def test_flush_elimina_todas_las_filas_y_seed_recupera_catalogo(
    mantenimiento_client: TestClient,
    session: Session,
    ruta: str,
) -> None:
    datos = crear_datos(session)
    crear_compromiso(session, datos)
    verificar_diferidas(session)
    session.commit()
    revision = session.scalar(text("SELECT version_num FROM alembic_version"))
    tablas = set(inspect(session.get_bind()).get_table_names())
    respuesta = mantenimiento_client.post(
        "/api/v1/mantenimiento/flush", headers=HEADERS
    )
    assert respuesta.status_code == 200
    assert set(inspect(session.get_bind()).get_table_names()) == tablas
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == revision
    for tabla in Base.metadata.tables.values():
        assert session.scalar(select(func.count()).select_from(tabla)) == 0, tabla.name
    # La contraseña sigue funcionando después de borrar todas las cuentas.
    assert (
        mantenimiento_client.post(
            "/api/v1/mantenimiento/flush", headers=HEADERS
        ).status_code
        == 200
    )
    recuperado = mantenimiento_client.post(
        f"/api/v1/mantenimiento/{ruta}",
        headers=HEADERS,
        **({"json": MASIVO} if ruta == "seed-masivo" else {}),
    )
    assert recuperado.status_code == 200
    assert session.scalar(select(func.count()).select_from(Unidad)) == 31
    assert session.scalar(select(func.count()).select_from(Capacidad)) == 56
    assert session.scalar(select(func.count()).select_from(Ong)) == 2


@pytest.mark.parametrize("ruta", RUTAS)
def test_error_de_commit_revierte_y_no_expone_detalles(
    mantenimiento_client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    ruta: str,
) -> None:
    datos = crear_datos(session)
    verificar_diferidas(session)
    session.commit()
    ong_id = datos.ong.id
    commit = Mock(side_effect=SQLAlchemyError(f"SQL privado con {PASSWORD}"))
    monkeypatch.setattr(session, "commit", commit)
    respuesta = mantenimiento_client.post(
        f"/api/v1/mantenimiento/{ruta}",
        headers=HEADERS,
        json=MASIVO,
    )
    assert respuesta.status_code == 503
    commit.assert_called_once()
    assert PASSWORD not in respuesta.text and "SQL" not in respuesta.text
    assert session.get(Ong, ong_id) is not None
    assert session.scalar(select(func.count()).select_from(Ong)) == 1
    assert session.get(Cuenta, ADMIN_DEMO_ID) is None


def test_colision_revierte_admin_y_ongs_parciales(
    mantenimiento_client: TestClient,
    session: Session,
) -> None:
    datos = crear_datos(session)
    datos.admin.identificador_login = "ong@rescuesync.org"
    session.commit()
    respuesta = mantenimiento_client.post("/api/v1/mantenimiento/seed", headers=HEADERS)
    assert respuesta.status_code == 409
    assert session.get(Cuenta, ADMIN_DEMO_ID) is None
    assert session.scalar(select(func.count()).select_from(Ong)) == 1


@pytest.mark.parametrize(
    "datos",
    [
        {"ongs": 0},
        {"ongs": True},
        {"ongs": 10_001},
        {"recursosPorOng": 3},
        {"ongs": 1000, "recursosPorOng": 201},
        {"batchSize": 1001},
        {"seed": -1},
        {"permitirProduccion": True},
    ],
)
def test_masivo_invalido_no_escribe(
    mantenimiento_client: TestClient,
    session: Session,
    datos: dict[str, object],
) -> None:
    respuesta = mantenimiento_client.post(
        "/api/v1/mantenimiento/seed-masivo",
        headers=HEADERS,
        json=datos,
    )
    assert respuesta.status_code == 422
    assert session.scalar(select(func.count()).select_from(Cuenta)) == 0


@pytest.mark.parametrize("ruta", RUTAS)
def test_mantenimiento_espera_lock_de_otra_conexion_y_no_escribe_al_expirar(
    client: TestClient,
    engine_migrado: Engine,
    monkeypatch: pytest.MonkeyPatch,
    ruta: str,
) -> None:
    monkeypatch.setattr(get_settings(), "db_maintenance_password", SecretStr(PASSWORD))
    monkeypatch.setattr(get_settings(), "operacion_lock_timeout_ms", 40)
    with Session(engine_migrado) as bloqueante, Session(engine_migrado) as db:
        bloqueante.execute(text("SELECT pg_advisory_xact_lock(73844, 0)"))

        def database() -> Iterator[Session]:
            yield db

        app.dependency_overrides[get_db] = database
        respuesta = client.post(
            f"/api/v1/mantenimiento/{ruta}", headers=HEADERS, json=MASIVO
        )
        assert respuesta.status_code == 503
        assert db.scalar(select(func.count()).select_from(Cuenta)) == 0
        assert db.scalar(select(func.count()).select_from(Capacidad)) == 56
        bloqueante.rollback()


def test_seed_masivo_sin_cuerpo_usa_volumen_predeterminado(
    mantenimiento_client: TestClient,
) -> None:
    respuesta = mantenimiento_client.post(
        "/api/v1/mantenimiento/seed-masivo", headers=HEADERS
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "operacion": "seed-masivo",
        "mensaje": "Seed masivo confirmado.",
        "ongs": 1000,
        "cuentas": 2001,
        "recursos": 20000,
    }
