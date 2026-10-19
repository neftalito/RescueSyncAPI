"""Consultas protegidas; la carga oficial se realiza mediante el CLI administrativo."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.dependencies import CuentaActual, Db
from app.db.models import NivelRiesgo, RolNacional
from app.schemas.certificaciones import (
    CertificacionesOngResponse,
    CertificacionResponse,
)
from app.schemas.inventario import ErrorResponse
from app.services.certificaciones import (
    CertificacionNoEncontradaError,
    consultar_certificaciones_ong,
    listar_certificaciones,
)

router = APIRouter()
errores = {codigo: {"model": ErrorResponse} for codigo in (401, 403, 404, 422)}


@router.get(
    "/certificaciones",
    response_model=list[CertificacionResponse],
    responses=errores,
    summary="Consultar catálogo de certificaciones y alcances",
    description=(
        "Los filtros seleccionan revisiones con alcances compatibles; "
        "no acreditan a la cuenta consultante."
    ),
)
def catalogo(
    session: Db,
    cuenta: CuentaActual,
    response: Response,
    capacidad_id: Annotated[UUID | None, Query(alias="capacidadId")] = None,
    nivel_riesgo: Annotated[NivelRiesgo | None, Query(alias="nivelRiesgo")] = None,
    incluir_inactivas: Annotated[bool, Query(alias="incluirInactivas")] = False,
) -> list[CertificacionResponse]:
    if incluir_inactivas and cuenta.rol != RolNacional.ADMIN_NACIONAL:
        raise HTTPException(
            403, "Sólo la administración consulta revisiones inactivas."
        )
    response.headers["Cache-Control"] = "no-store"
    return listar_certificaciones(
        session,
        capacidad_id=capacidad_id,
        nivel_riesgo=nivel_riesgo,
        incluir_inactivas=incluir_inactivas,
    )


@router.get(
    "/ongs/{ong_id}/certificaciones",
    response_model=CertificacionesOngResponse,
    responses=errores,
    summary="Consultar acreditaciones y competencia de una ONG",
    description=(
        "Incluye historia y motivos. La competencia se evalúa en UTC "
        "y no garantiza stock ni compromiso futuro."
    ),
)
def acreditaciones(
    ong_id: UUID, session: Db, cuenta: CuentaActual, response: Response
) -> CertificacionesOngResponse:
    if cuenta.rol == RolNacional.ONG and cuenta.ong_id != ong_id:
        raise HTTPException(403, "Sólo podés consultar las acreditaciones de tu ONG.")
    response.headers["Cache-Control"] = "no-store"
    try:
        return consultar_certificaciones_ong(session, ong_id)
    except CertificacionNoEncontradaError as error:
        raise HTTPException(404, str(error)) from error
