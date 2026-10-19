"""Validación nacional transitoria del snapshot cerrado que Bonita obtiene de T34."""

import logging

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import CuentaEvaluacion, DbEvaluacion
from app.schemas.inventario import ErrorResponse
from app.schemas.validaciones import ValidacionRequest, ValidacionResponse
from app.services.disponibilidad import InventarioInconsistenteError
from app.services.emisores import (
    EmisorDenegadoError,
    EmisorNoEncontradoError,
    autorizar_emisor,
)
from app.services.validaciones import validar_snapshot

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/validaciones",
    response_model=ValidacionResponse,
    summary="Evaluar competencias y disponibilidad por aporte sin reservar",
    description=(
        "Recibe el contrato 2 de T34 después del cierre. Devuelve capacidades, "
        "riesgos, perfiles PRINCIPAL/APOYO/SIN_HABILITACION y motivos por ONG. "
        "La disponibilidad consultada no garantiza stock al adjudicar. "
        "No guarda ofertas ni crea proyectos o compromisos."
    ),
    responses={c: {"model": ErrorResponse} for c in (401, 403, 404, 422, 500, 503)},
)
def validar(
    snapshot: ValidacionRequest,
    session: DbEvaluacion,
    cuenta: CuentaEvaluacion,
    response: Response,
) -> ValidacionResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        autorizar_emisor(session, cuenta, snapshot.sistema_origen)
        return validar_snapshot(session, snapshot)
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except EmisorNoEncontradoError as error:
        raise HTTPException(404, str(error)) from error
    except InventarioInconsistenteError as error:
        logger.error("No se pudo evaluar por inconsistencia del inventario nacional.")
        raise HTTPException(500, "El inventario nacional no es consistente.") from error
    except SQLAlchemyError as error:
        session.rollback()
        logger.error("No se pudo consultar la base nacional para evaluar.")
        raise HTTPException(
            503, "La evaluación nacional no está disponible."
        ) from error
