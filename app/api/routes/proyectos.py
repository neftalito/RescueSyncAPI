"""Cierre nacional protegido por emisor, caso e idempotencia."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Path, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api import ejemplos
from app.api.dependencies import CuentaActual, Db, IdempotencyKey
from app.api.documentacion import respuestas
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
        "Acceso: INTEGRACION del emisor dueño o ADMIN_NACIONAL; cuentas ONG "
        "reciben 403. Exige caseId del proyecto e Idempotency-Key. Toma el "
        "mismo lock de proyecto que comprometer; con compromisos activos "
        "devuelve 409 sin liberar recursos. Sin activos pasa a TERMINADO, "
        "estado terminal que impide nuevas reservas. Los reintentos conservan"
        " el primer cierre; misma clave con otro destino/caso produce 409. "
        "Tras timeout, reintentar la misma clave."
    ),
    responses=respuestas(
        401, 403, 404, 409, 422, 503, ejemplo=ejemplos.CIERRE, exito=200
    ),
)
def cerrar(
    proyecto_id: Annotated[
        UUID,
        Path(
            description="UUID nacional del proyecto devuelto al comprometer.",
            examples=[ejemplos.PROYECTO_ID],
        ),
    ],
    datos: Annotated[FinalizacionRequest, Body(examples=[ejemplos.FINALIZACION])],
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
