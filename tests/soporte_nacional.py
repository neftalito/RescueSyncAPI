"""Fixtures compartidas de identidades nacionales y autenticación JWT."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_database_models import DatosNacionales, crear_datos

from app.core.security import emitir_token
from app.db.models import (
    Cuenta,
    RolNacional,
)
from app.db.session import get_db, get_db_evaluacion
from app.main import app


@pytest.fixture
def datos(session: Session) -> DatosNacionales:
    datos = crear_datos(session, f"cert-{uuid4().hex}")
    session.commit()
    return datos


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def database() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_db_evaluacion] = database
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()


def auth(cuenta: Cuenta) -> dict[str, str]:
    return {"Authorization": f"Bearer {emitir_token(cuenta.id)}"}


def cuenta_ong(session: Session, datos: DatosNacionales) -> Cuenta:
    cuenta = Cuenta(
        identificador_login=f"ong-{uuid4()}@example.test",
        ong_id=datos.ong.id,
        rol=RolNacional.ONG,
        password_hash="$argon2id$hash-de-prueba",
    )
    session.add(cuenta)
    session.commit()
    return cuenta
