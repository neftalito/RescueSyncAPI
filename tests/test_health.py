from collections.abc import Iterator
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app


def reemplazar_sesion(session: Session) -> None:
    """Reemplaza PostgreSQL por una sesión controlada durante una prueba."""

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = override


def test_root_publica_enlaces_de_descubrimiento(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "RescueSync API Nacional",
        "version": "0.1.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/api/v1/health",
    }


def test_liveness_no_depende_de_postgresql(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "national-api"}


def test_readiness_consulta_postgresql_real(client: TestClient) -> None:
    response = client.get("/api/v1/health/database")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "national-api"}


def test_readiness_confirma_conexion_a_postgresql(client: TestClient) -> None:
    session = Mock(spec=Session)
    reemplazar_sesion(session)

    response = client.get("/api/v1/health/database")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "national-api"}
    session.execute.assert_called_once()


def test_readiness_oculta_el_error_de_postgresql(client: TestClient) -> None:
    session = Mock(spec=Session)
    session.execute.side_effect = SQLAlchemyError("password=secreto-interno")
    reemplazar_sesion(session)

    response = client.get("/api/v1/health/database")

    assert response.status_code == 503
    assert response.json() == {"detail": "PostgreSQL no está disponible"}
    assert "secreto-interno" not in response.text


def test_openapi_documenta_solo_las_rutas_versionadas(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()

    assert "/" not in schema["paths"]
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/health/database" in schema["paths"]


def test_interfaces_de_documentacion_estan_disponibles(
    client: TestClient,
) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
