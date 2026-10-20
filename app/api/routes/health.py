import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import ejemplos
from app.api.documentacion import respuestas
from app.db.session import get_db
from app.schemas.health import HealthResponse

router = APIRouter()
LOGGER = logging.getLogger(__name__)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get(
    "",
    response_model=HealthResponse,
    summary="Comprobar el proceso HTTP",
    description=("Acceso público. Comprueba el proceso HTTP sin consultar PostgreSQL."),
    responses=respuestas(ejemplo=ejemplos.HEALTH, exito=200),
)
def health() -> HealthResponse:
    """Indica que el proceso de la API se encuentra en ejecución."""

    return HealthResponse(service="national-api")


@router.get(
    "/database",
    response_model=HealthResponse,
    summary="Comprobar PostgreSQL",
    description=(
        "Acceso público. Comprueba una conexión real a PostgreSQL. Fallo "
        "temporal devuelve 503 con JSON detail seguro, sin exponer "
        "infraestructura."
    ),
    responses=respuestas(
        503,
        ejemplo=ejemplos.HEALTH,
        exito=200,
        detalles={503: "PostgreSQL no está disponible"},
    ),
)
def database_health(session: DatabaseSession) -> HealthResponse:
    """Comprueba una conexión real sin publicar detalles de infraestructura."""

    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        LOGGER.warning("PostgreSQL no está disponible para el health check")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL no está disponible",
        ) from exc

    return HealthResponse(service="national-api")
