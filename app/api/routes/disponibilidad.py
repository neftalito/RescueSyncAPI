"""Consulta global JWT de stock operativo sin garantía de reserva futura."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.dependencies import CuentaActual, Db
from app.schemas.disponibilidad import DisponibilidadResponse
from app.schemas.inventario import ErrorResponse
from app.services.disponibilidad import (
    InventarioInconsistenteError,
    consultar_disponibilidad,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/recursos/disponibilidad",
    response_model=DisponibilidadResponse,
    responses={codigo: {"model": ErrorResponse} for codigo in (401, 403, 422, 500)},
    summary="Consultar disponibilidad global por capacidad y ONG",
    description=(
        "Stock de recursos y capacidades activos de instituciones HABILITADAS. "
        "Descuenta sólo compromisos activos, conserva disponibilidad cero y "
        "separa capacidad/unidad. No evalúa certificaciones ni reserva stock. "
        "Las cuentas ONG, administración e integración consultan agregados resumidos."
    ),
)
def disponibilidad(
    session: Db,
    cuenta: CuentaActual,
    response: Response,
    capacidad_id: Annotated[UUID | None, Query(alias="capacidadId")] = None,
    ong_id: Annotated[UUID | None, Query(alias="ongId")] = None,
) -> DisponibilidadResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return consultar_disponibilidad(
            session, capacidad_id=capacidad_id, ong_id=ong_id
        )
    except InventarioInconsistenteError as error:
        logger.error("El inventario nacional contiene disponibilidad inconsistente.")
        raise HTTPException(500, "No se pudo consultar la disponibilidad.") from error
