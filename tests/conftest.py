from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Entrega un cliente aislado y limpia reemplazos de dependencias."""

    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def engine_vacio() -> Iterator[Engine]:
    """Crea sólo un schema aleatorio; nunca baja tablas de una base existente."""

    settings = Settings(_env_file=None)
    if settings.app_env != "test":
        pytest.fail("Las pruebas de integridad requieren APP_ENV=test")
    schema = f"test_nacional_{uuid4().hex}"
    admin_engine = create_engine(settings.sqlalchemy_database_uri)
    with admin_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = create_engine(
        settings.sqlalchemy_database_uri,
        connect_args={"options": f"-c search_path={schema} -c timezone=UTC"},
    )
    try:
        yield isolated
    finally:
        isolated.dispose()
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


@pytest.fixture(scope="module")
def engine_migrado(engine_vacio: Engine) -> Engine:
    """Aplica la migración real, sin usar Base.metadata.create_all()."""

    with engine_vacio.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "alembic"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return engine_vacio


@pytest.fixture
def session(engine_migrado: Engine) -> Iterator[Session]:
    """Cada prueba revierte su transacción; el schema se elimina al finalizar."""

    with engine_migrado.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            try:
                yield db
            finally:
                db.rollback()
        transaction.rollback()
