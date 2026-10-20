"""Consulta JWT del directorio nacional resumido de instituciones habilitadas."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api import ejemplos
from app.api.dependencies import CuentaActual, Db
from app.api.documentacion import respuestas
from app.db.models import NivelRiesgo
from app.schemas.ongs import OngsHabilitadasResponse
from app.services.ongs import listar_ongs_habilitadas

router = APIRouter()


@router.get(
    "/ongs/habilitadas",
    response_model=OngsHabilitadasResponse,
    summary="Consultar ONGs habilitadas y sus competencias vigentes",
    description=(
        "Acceso: ONG, ADMIN_NACIONAL o INTEGRACION con cuenta vigente. "
        "Directorio resumido sin datos de contacto. Sin filtros incluye "
        "instituciones habilitadas sin competencias. Capacidad y riesgo "
        "coinciden en un mismo alcance; devuelve perfil completo. No consulta"
        " stock ni reserva recursos."
    ),
    responses=respuestas(401, 403, 422, ejemplo=ejemplos.ONGS_HABILITADAS, exito=200),
)
def ongs_habilitadas(
    session: Db,
    cuenta: CuentaActual,
    response: Response,
    capacidad_id: Annotated[
        UUID | None,
        Query(
            alias="capacidadId",
            description="UUID de capacidad nacional; filtra recursos o alcances.",
            examples=[ejemplos.CAPACIDAD_ID],
        ),
    ] = None,
    nivel_riesgo: Annotated[
        NivelRiesgo | None,
        Query(
            alias="nivelRiesgo",
            description="Riesgo requerido: BAJA, MEDIA, ALTA o CRITICA.",
            examples=["MEDIA"],
        ),
    ] = None,
) -> OngsHabilitadasResponse:
    response.headers["Cache-Control"] = "no-store"
    return listar_ongs_habilitadas(
        session, capacidad_id=capacidad_id, nivel_riesgo=nivel_riesgo
    )
