"""Compromiso nacional atómico y consulta autenticada para reconciliar resultados."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import CuentaActual, Db, IdempotencyKey
from app.schemas.compromisos import (
    CompromisoRequest,
    CompromisoResponse,
    ConfirmacionCompromisos,
)
from app.schemas.inventario import ErrorResponse
from app.schemas.proyectos import ConfirmacionLiberacion, FinalizacionRequest
from app.services.compromisos import consultar_compromiso, registrar_compromisos
from app.services.disponibilidad import InventarioInconsistenteError
from app.services.emisores import EmisorDenegadoError, EmisorNoEncontradoError
from app.services.liberaciones import liberar_compromiso
from app.services.operaciones import ErrorOperacion

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/compromisos/{compromiso_id}/liberacion",
    response_model=ConfirmacionLiberacion,
    summary="Liberar una vez el compromiso de una ONG y conservar historial",
    description=(
        "Exige emisor, caso y clave idempotente. Una ONG suspendida o "
        "acreditación vencida no impiden liberar su reserva por el emisor autorizado."
    ),
    responses={c: {"model": ErrorResponse} for c in (401, 403, 404, 409, 422, 503)},
)
def liberar(
    compromiso_id: UUID,
    datos: FinalizacionRequest,
    clave: IdempotencyKey,
    session: Db,
    cuenta: CuentaActual,
    response: Response,
) -> ConfirmacionLiberacion:
    response.headers["Cache-Control"] = "no-store"
    try:
        return liberar_compromiso(session, cuenta, compromiso_id, datos, clave)
    except ErrorOperacion as error:
        raise HTTPException(error.status, str(error)) from error
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except SQLAlchemyError as error:
        logger.error("No se confirmó la liberación; reintentar con la misma clave.")
        raise HTTPException(
            503, "Liberación temporalmente no disponible. Reintentá con la misma clave."
        ) from error


@router.post(
    "/compromisos",
    response_model=ConfirmacionCompromisos,
    status_code=201,
    summary="Comprometer atómicamente cantidades adjudicadas por ONG",
    description=(
        "Revalida competencias y stock bajo locks. Idempotency-Key identifica "
        "la selección completa del emisor; no guarda el cuerpo de ofertas."
    ),
    responses={c: {"model": ErrorResponse} for c in (401, 403, 404, 409, 422, 503)},
)
def comprometer(
    datos: CompromisoRequest,
    clave: IdempotencyKey,
    session: Db,
    cuenta: CuentaActual,
    response: Response,
) -> ConfirmacionCompromisos:
    response.headers["Cache-Control"] = "no-store"
    try:
        return registrar_compromisos(session, cuenta, datos, clave)
    except ErrorOperacion as error:
        raise HTTPException(error.status, str(error)) from error
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except EmisorNoEncontradoError as error:
        raise HTTPException(404, str(error)) from error
    except InventarioInconsistenteError as error:
        logger.error("No se confirmó por inconsistencia del inventario nacional.")
        raise HTTPException(500, "El inventario nacional no es consistente.") from error
    except SQLAlchemyError as error:
        logger.error(
            "No se confirmó el compromiso nacional; reintentar con la misma clave."
        )
        raise HTTPException(
            503, "Operación temporalmente no disponible. Reintentá con la misma clave."
        ) from error


@router.get(
    "/compromisos/{compromiso_id}",
    response_model=CompromisoResponse,
    summary="Consultar el estado vigente y referencias de un compromiso",
    responses={c: {"model": ErrorResponse} for c in (401, 403, 404, 422, 503)},
)
def consultar(
    compromiso_id: UUID, session: Db, cuenta: CuentaActual, response: Response
) -> CompromisoResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return consultar_compromiso(session, cuenta, compromiso_id)
    except ErrorOperacion as error:
        raise HTTPException(error.status, str(error)) from error
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except SQLAlchemyError as error:
        session.rollback()
        logger.error("No se pudo consultar un compromiso nacional.")
        raise HTTPException(503, "La consulta nacional no está disponible.") from error
