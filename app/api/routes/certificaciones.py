"""Consultas protegidas; la carga oficial se realiza mediante el CLI administrativo."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Response

from app.api import ejemplos
from app.api.dependencies import CuentaActual, Db
from app.api.documentacion import respuestas
from app.db.models import NivelRiesgo, RolNacional
from app.schemas.certificaciones import (
    CertificacionesOngResponse,
    CertificacionResponse,
)
from app.services.certificaciones import (
    CertificacionNoEncontradaError,
    consultar_certificaciones_ong,
    listar_certificaciones,
)

router = APIRouter()


@router.get(
    "/certificaciones",
    response_model=list[CertificacionResponse],
    summary="Consultar catálogo de certificaciones y alcances",
    description=(
        "Acceso: ONG, ADMIN_NACIONAL o INTEGRACION. Sólo ADMIN_NACIONAL "
        "admite incluirInactivas=true; otros roles reciben 403. Los filtros "
        "seleccionan alcances compatibles y no acreditan a la cuenta "
        "consultante."
    ),
    responses=respuestas(401, 403, 422, ejemplo=[ejemplos.CERTIFICACION], exito=200),
)
def catalogo(
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
    incluir_inactivas: Annotated[
        bool,
        Query(
            alias="incluirInactivas",
            description="Revisiones inactivas: sólo ADMIN_NACIONAL.",
            examples=[False],
        ),
    ] = False,
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
    summary="Consultar acreditaciones y competencia de una ONG",
    description=(
        "Acceso: ONG propia, ADMIN_NACIONAL o INTEGRACION. Otra ONG recibe "
        "403. Incluye historia, vigencia UTC [desde,hasta), capacidades y "
        "motivos. No garantiza disponibilidad ni reserva futura."
    ),
    responses=respuestas(
        401, 403, 404, 422, ejemplo=ejemplos.CERTIFICACIONES_ONG, exito=200
    ),
)
def acreditaciones(
    ong_id: Annotated[
        UUID,
        Path(
            description="UUID de la ONG en el sistema nacional; no es el ID local.",
            examples=[ejemplos.ONG_ID],
        ),
    ],
    session: Db,
    cuenta: CuentaActual,
    response: Response,
) -> CertificacionesOngResponse:
    if cuenta.rol == RolNacional.ONG and cuenta.ong_id != ong_id:
        raise HTTPException(403, "Sólo podés consultar las acreditaciones de tu ONG.")
    response.headers["Cache-Control"] = "no-store"
    try:
        return consultar_certificaciones_ong(session, ong_id)
    except CertificacionNoEncontradaError as error:
        raise HTTPException(404, str(error)) from error
