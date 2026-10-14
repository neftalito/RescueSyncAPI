"""Cierre nacional protegido por emisor, caso e idempotencia."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import CuentaActual, Db, IdempotencyKey
from app.schemas.inventario import ErrorResponse
from app.schemas.proyectos import ConfirmacionCierre, FinalizacionRequest
from app.services.emisores import EmisorDenegadoError
from app.services.operaciones import ErrorOperacion
from app.services.proyectos import cerrar_proyecto

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/proyectos/{proyecto_id}/cierre",
    response_model=ConfirmacionCierre,
    summary="Cerrar un proyecto únicamente sin compromisos activos",
    description=(
        "Comparte el lock de proyecto con el compromiso transaccional. "
        "No libera recursos ni modifica el cierre confirmado al repetir."
    ),
    responses={c: {"model": ErrorResponse} for c in (401, 403, 404, 409, 422, 503)},
)
def cerrar(
    proyecto_id: UUID,
    datos: FinalizacionRequest,
    clave: IdempotencyKey,
    session: Db,
    cuenta: CuentaActual,
    response: Response,
) -> ConfirmacionCierre:
    response.headers["Cache-Control"] = "no-store"
    try:
        return cerrar_proyecto(session, cuenta, proyecto_id, datos, clave)
    except ErrorOperacion as error:
        raise HTTPException(error.status, str(error)) from error
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except SQLAlchemyError as error:
        logger.error(
            "No se confirmó el cierre nacional; reintentar con la misma clave."
        )
        raise HTTPException(
            503, "Cierre temporalmente no disponible. Reintentá con la misma clave."
        ) from error
