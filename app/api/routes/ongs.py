"""Consulta JWT del directorio nacional resumido de instituciones habilitadas."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.dependencies import CuentaActual, Db
from app.db.models import NivelRiesgo
from app.schemas.inventario import ErrorResponse
from app.schemas.ongs import OngsHabilitadasResponse
from app.services.ongs import listar_ongs_habilitadas

router = APIRouter()


@router.get(
    "/ongs/habilitadas",
    response_model=OngsHabilitadasResponse,
    responses={codigo: {"model": ErrorResponse} for codigo in (401, 403, 422)},
    summary="Consultar ONGs habilitadas y sus competencias vigentes",
    description=(
        "Directorio resumido para cuentas ONG, administración e integración. "
        "Sin filtros incluye instituciones habilitadas sin competencias. "
        "Capacidad y riesgo deben coincidir en un mismo alcance; se devuelve "
        "el perfil completo. No consulta stock ni reserva recursos."
    ),
)
def ongs_habilitadas(
    session: Db,
    cuenta: CuentaActual,
    response: Response,
    capacidad_id: Annotated[UUID | None, Query(alias="capacidadId")] = None,
    nivel_riesgo: Annotated[NivelRiesgo | None, Query(alias="nivelRiesgo")] = None,
) -> OngsHabilitadasResponse:
    response.headers["Cache-Control"] = "no-store"
    return listar_ongs_habilitadas(
        session, capacidad_id=capacidad_id, nivel_riesgo=nivel_riesgo
    )
